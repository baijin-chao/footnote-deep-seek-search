"""离线演示入口：回放已录制的演示问题。

批处理里不能直接写中文（cmd 按 GBK 解析会乱），所以把问题放在这个 Python 文件里。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_QUESTION = "向量数据库常见的索引类型有哪些？"

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    fixtures = REPO_ROOT / "fixtures"
    if not (fixtures / "llm").exists():
        print("[ERROR] fixtures/ 里没有录制内容，无法离线演示。")
        print("请先在有网络时录制一次：")
        print("  scripts\\run.cmd \"向量数据库常见的索引类型有哪些？\" --mode record --no-cache")
        return 1

    from dra.main import main as cli_main

    return cli_main([DEMO_QUESTION, "--mode", "mock", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
