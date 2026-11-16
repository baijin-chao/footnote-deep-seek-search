"""搜索缓存：按 (provider, query) 缓存搜索结果。

搜索 API 有免费额度，评测要反复跑同一批题，缓存能让重跑接近零消耗。
缓存放 SQLite，与主库同一个文件，便于随 .work 一起清理。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .verify import tokenize

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    cache_key  TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    query      TEXT NOT NULL,
    results    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_cache_provider ON search_cache(provider);
"""

# 近似匹配阈值：低于此值不认为缓存可用，避免把不同问题误判为同一个
DEFAULT_SIMILARITY = 0.8

# 反义词组：两条查询分别命中同一组的两个词时，禁止近似命中
ANTONYM_PAIRS = (
    ("优势", "劣势"),
    ("优点", "缺点"),
    ("好处", "坏处"),
    ("提升", "下降"),
    ("增加", "减少"),
    ("适用", "不适用"),
)


_STRIP_CHARS = "？?。.，,；;：:！!、（）()「」“”\"' \t\n"


def normalize_query(query: str) -> str:
    """归一化查询串，提高缓存命中率。

    做两件事：压缩空白、去掉首尾标点。不做同义词或分词级归一——那属于语义匹配，
    会把不同问题误判为同一个，风险大于收益。
    """
    text = " ".join((query or "").split()).strip()
    return text.strip(_STRIP_CHARS)


def make_key(provider: str, query: str) -> str:
    raw = f"{provider}|{normalize_query(query)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    """两个查询串的相似度，取 Jaccard 与包含度的较大值。

    只用 Jaccard 对「长度差异较大的改写」过于苛刻；包含度能覆盖
    「短查询是长查询的一部分」这种常见情况。
    """
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    jaccard = inter / len(ta | tb)
    containment = inter / min(len(ta), len(tb))
    return max(jaccard, containment)


def has_antonym_conflict(a: str, b: str) -> bool:
    """两条查询是否出现「优势 / 劣势」这类语义相反的词。"""
    return any((x in a and y in b) or (y in a and x in b) for x, y in ANTONYM_PAIRS)


class SearchCache:
    """带 TTL 的搜索缓存。

    命中规则：先按 (provider, 归一化 query) 精确命中；未命中时，在同一 provider 下
    找相似度 ≥ similarity 的历史查询。后者解决「同一问题的子问题措辞每次略有不同」
    导致缓存几乎不命中的问题。

    hits / misses / fuzzy_hits 用于统计，评测报告会展示，方便判断这轮花了多少额度。
    """

    def __init__(self, db_path: Path, ttl_days: float = 7.0, similarity_threshold: float = DEFAULT_SIMILARITY) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(0.0, ttl_days) * 86400
        self.similarity_threshold = similarity_threshold
        self.hits = 0
        self.misses = 0
        self.fuzzy_hits = 0
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _fresh(self, created_at: float) -> bool:
        return not (self.ttl_seconds and (time.time() - float(created_at)) > self.ttl_seconds)

    def get(self, provider: str, query: str) -> list[dict[str, Any]] | None:
        key = make_key(provider, query)
        row = self.conn.execute(
            "SELECT results, created_at FROM search_cache WHERE cache_key=?", (key,)
        ).fetchone()
        if row is not None and self._fresh(row[1]):
            self.hits += 1
            return self._load(row[0])

        # 近似匹配：同一 provider 下找最相似且未过期的历史查询
        best_score, best_payload = 0.0, None
        for stored_query, results_raw, created_at in self.conn.execute(
            "SELECT query, results, created_at FROM search_cache WHERE provider=?", (provider,)
        ):
            if not self._fresh(created_at):
                continue
            score = similarity(query, stored_query)
            if score <= best_score or has_antonym_conflict(query, stored_query):
                continue
            best_score, best_payload = score, results_raw

        if best_payload is not None and best_score >= self.similarity_threshold:
            self.hits += 1
            self.fuzzy_hits += 1
            return self._load(best_payload)

        self.misses += 1
        return None

    @staticmethod
    def _load(payload: str) -> list[dict[str, Any]] | None:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def put(self, provider: str, query: str, results: list[dict[str, Any]]) -> None:
        key = make_key(provider, query)
        self.conn.execute(
            "INSERT OR REPLACE INTO search_cache (cache_key, provider, query, results, created_at)"
            " VALUES (?,?,?,?,?)",
            (key, provider, normalize_query(query), json.dumps(results, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "fuzzy_hits": self.fuzzy_hits,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
