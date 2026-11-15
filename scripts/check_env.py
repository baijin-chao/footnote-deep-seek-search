#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查 .env 配置与外部服务连通性。

只用标准库，不需要安装任何依赖：
    python scripts/check_env.py

退出码 0 = 全部通过；1 = 有缺失或调用失败。
不会打印完整密钥，只显示前 6 位。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

REQUIRED = ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "SEARCH_PROVIDER", "SEARCH_API_KEY"]

OK, BAD, SKIP = "[ OK ]", "[FAIL]", "[SKIP]"


def setup_stdout() -> None:
    """统一输出为 UTF-8，避免 Windows 终端编码不一致导致乱码。"""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def mask(secret: str) -> str:
    if not secret:
        return "<空>"
    return secret[:6] + "*" * max(0, len(secret) - 6)


def http_json(url: str, payload: dict | None, headers: dict, timeout: int = 20) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        snippet = e.read().decode("utf-8", "replace")[:300]
        return e.code, {"_error": snippet}
    except Exception as e:  # 网络不可达 / TLS / 超时
        return -1, {"_error": f"{type(e).__name__}: {e}"}


def main() -> int:
    setup_stdout()
    env = load_env(ENV_PATH)
    failures: list[str] = []

    print(f"配置文件: {ENV_PATH}  ({'存在' if ENV_PATH.exists() else '不存在'})")
    print(f"运行模式: RUN_MODE={env.get('RUN_MODE', '<未设置>')}\n")

    # 1) 必填项
    print("== 1. 必填项检查 ==")
    for key in REQUIRED:
        val = env.get(key, "")
        if val:
            print(f"{OK} {key} = {mask(val) if 'KEY' in key else val}")
        else:
            print(f"{BAD} {key} 未填写")
            failures.append(f"{key} 未填写")
    for opt in ("BOCHA_API_KEY",):
        print(f"{OK if env.get(opt) else SKIP} {opt} = {mask(env.get(opt, ''))}（可选，用于降级）")

    # 2) LLM 连通性
    print("\n== 2. LLM 连通性 ==")
    key = env.get("LLM_API_KEY", "")
    base = env.get("LLM_BASE_URL", "").rstrip("/")
    if not key or not base:
        print(f"{SKIP} 缺少 LLM_API_KEY 或 LLM_BASE_URL")
    else:
        status, body = http_json(f"{base}/models", None, {"Authorization": f"Bearer {key}"})
        if status == 200:
            models = [m.get("id") for m in body.get("data", [])][:5]
            print(f"{OK} {base}/models 返回 200，可用模型示例: {models}")
            want = env.get("LLM_MODEL", "")
            if want and models and want not in models:
                print(f"{BAD} 配置的 LLM_MODEL={want} 不在返回列表中")
                failures.append(f"LLM_MODEL={want} 不存在")
            strong = env.get("LLM_MODEL_STRONG", "")
            if strong and models and strong not in models:
                print(f"{BAD} 配置的 LLM_MODEL_STRONG={strong} 不在返回列表中")
                failures.append(f"LLM_MODEL_STRONG={strong} 不存在")
        else:
            print(f"{BAD} {base}/models 返回 {status}: {body.get('_error', body)}")
            failures.append("LLM 调用失败")

    # 3) 搜索连通性
    print("\n== 3. 搜索连通性 ==")
    provider = env.get("SEARCH_PROVIDER", "").lower()
    if provider == "tavily":
        search_key = env.get("SEARCH_API_KEY", "")
        if not search_key:
            print(f"{SKIP} SEARCH_API_KEY 未填写")
        else:
            status, body = http_json(
                "https://api.tavily.com/search",
                {"api_key": search_key, "query": "deepseek", "max_results": 1},
                {"Content-Type": "application/json"},
            )
            if status == 200 and body.get("results"):
                title = body["results"][0].get("title", "")[:40]
                print(f"{OK} Tavily 返回 {len(body['results'])} 条结果，首条: {title}")
            else:
                print(f"{BAD} Tavily 返回 {status}: {body.get('_error', body)}")
                failures.append("Tavily 调用失败")
    elif provider == "bocha":
        bkey = env.get("BOCHA_API_KEY", "")
        if not bkey:
            print(f"{SKIP} BOCHA_API_KEY 未填写")
        else:
            status, body = http_json(
                "https://api.bochaai.com/v1/web-search",
                {"query": "deepseek", "count": 1, "summary": True},
                {"Authorization": f"Bearer {bkey}", "Content-Type": "application/json"},
            )
            if status == 200:
                print(f"{OK} 博查返回 200")
            else:
                print(f"{BAD} 博查返回 {status}: {body.get('_error', body)}")
                failures.append("博查调用失败")
    else:
        print(f"{BAD} SEARCH_PROVIDER 配置未知: {provider!r}（应为 tavily 或 bocha）")
        failures.append("SEARCH_PROVIDER 非法")

    # 4) 汇总
    print("\n== 汇总 ==")
    if failures:
        print(f"{BAD} 未通过 {len(failures)} 项：")
        for f in failures:
            print(f"   - {f}")
        print("\n下一步：编辑 C:\\agent\\.env 填入密钥后重新运行本脚本。")
        return 1
    print(f"{OK} 全部通过，可以开始真实调用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
