"""配置加载：从仓库根目录的 .env 读取，缺失项回落默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_env(path: Path) -> dict[str, str]:
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


def _pick(env: dict[str, str], key: str, default, cast=str):
    raw = env.get(key) or os.environ.get(key) or ""
    if raw == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # 运行
    run_mode: str = "live"
    # LLM
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_model_strong: str = "deepseek-v4-pro"
    llm_api_key: str = ""
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_timeout: float = 60.0
    # 计价（美元 / 百万 token）
    price_main_in: float = 0.30
    price_main_out: float = 1.20
    price_strong_in: float = 1.32
    price_strong_out: float = 3.96
    usd_to_cny: float = 7.2
    # 搜索
    search_provider: str = "tavily"
    search_api_key: str = ""
    bocha_api_key: str = ""
    search_max_results: int = 8
    search_timeout: float = 20.0
    # 抓取
    fetch_timeout: float = 20.0
    fetch_max_bytes: int = 3_000_000
    # 预算
    budget_max_steps: int = 25
    budget_max_tokens: int = 60_000
    budget_max_cny: float = 0.6
    budget_max_seconds: float = 120.0
    reflect_max_rounds: int = 2
    # 存储
    db_path: Path = field(default_factory=lambda: REPO_ROOT / ".work" / "dra.db")
    trace_dir: Path = field(default_factory=lambda: REPO_ROOT / ".work" / "traces")
    fixtures_dir: Path = field(default_factory=lambda: REPO_ROOT / "fixtures")
    # web
    app_host: str = "127.0.0.1"
    app_port: int = 8710
    log_level: str = "INFO"

    @classmethod
    def load(cls, env_path: Path | None = None) -> "Settings":
        env = parse_env(env_path or REPO_ROOT / ".env")
        return cls(
            run_mode=_pick(env, "RUN_MODE", "live"),
            llm_base_url=_pick(env, "LLM_BASE_URL", cls.llm_base_url),
            llm_model=_pick(env, "LLM_MODEL", cls.llm_model),
            llm_model_strong=_pick(env, "LLM_MODEL_STRONG", cls.llm_model_strong),
            llm_api_key=_pick(env, "LLM_API_KEY", ""),
            llm_temperature=_pick(env, "LLM_TEMPERATURE", cls.llm_temperature, float),
            llm_max_tokens=_pick(env, "LLM_MAX_TOKENS", cls.llm_max_tokens, int),
            llm_timeout=_pick(env, "LLM_TIMEOUT", cls.llm_timeout, float),
            price_main_in=_pick(env, "PRICE_MAIN_INPUT", cls.price_main_in, float),
            price_main_out=_pick(env, "PRICE_MAIN_OUTPUT", cls.price_main_out, float),
            price_strong_in=_pick(env, "PRICE_STRONG_INPUT", cls.price_strong_in, float),
            price_strong_out=_pick(env, "PRICE_STRONG_OUTPUT", cls.price_strong_out, float),
            usd_to_cny=_pick(env, "USD_TO_CNY", cls.usd_to_cny, float),
            search_provider=_pick(env, "SEARCH_PROVIDER", "tavily").lower(),
            search_api_key=_pick(env, "SEARCH_API_KEY", ""),
            bocha_api_key=_pick(env, "BOCHA_API_KEY", ""),
            search_max_results=_pick(env, "SEARCH_MAX_RESULTS", cls.search_max_results, int),
            search_timeout=_pick(env, "SEARCH_TIMEOUT", cls.search_timeout, float),
            fetch_timeout=_pick(env, "FETCH_TIMEOUT", cls.fetch_timeout, float),
            fetch_max_bytes=_pick(env, "FETCH_MAX_BYTES", cls.fetch_max_bytes, int),
            budget_max_steps=_pick(env, "BUDGET_MAX_STEPS", cls.budget_max_steps, int),
            budget_max_tokens=_pick(env, "BUDGET_MAX_TOKENS", cls.budget_max_tokens, int),
            budget_max_cny=_pick(env, "BUDGET_MAX_CNY", cls.budget_max_cny, float),
            budget_max_seconds=_pick(env, "BUDGET_MAX_SECONDS", cls.budget_max_seconds, float),
            reflect_max_rounds=_pick(env, "REFLECT_MAX_ROUNDS", cls.reflect_max_rounds, int),
            db_path=REPO_ROOT / _pick(env, "DB_PATH", ".work/dra.db"),
            trace_dir=REPO_ROOT / _pick(env, "TRACE_DIR", ".work/traces"),
            fixtures_dir=REPO_ROOT / _pick(env, "FIXTURES_DIR", "fixtures"),
            app_host=_pick(env, "APP_HOST", "127.0.0.1"),
            app_port=_pick(env, "APP_PORT", 8710, int),
            log_level=_pick(env, "LOG_LEVEL", "INFO").upper(),
        )

    # ---- 计价 ----
    def prices(self, model: str) -> tuple[float, float]:
        """返回 (输入, 输出) 的美元单价（每百万 token）。"""
        if model == self.llm_model_strong:
            return self.price_strong_in, self.price_strong_out
        return self.price_main_in, self.price_main_out

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pin, pout = self.prices(model)
        return (tokens_in * pin + tokens_out * pout) / 1_000_000

    def cost_cny(self, model: str, tokens_in: int, tokens_out: int) -> float:
        return self.cost_usd(model, tokens_in, tokens_out) * self.usd_to_cny

    def ensure_dirs(self) -> None:
        for p in (self.db_path.parent, self.trace_dir, self.fixtures_dir):
            p.mkdir(parents=True, exist_ok=True)
