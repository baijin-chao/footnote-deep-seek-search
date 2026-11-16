"""搜索缓存的离线测试（不联网）。"""

from __future__ import annotations

import time

import pytest

from dra.cache import SearchCache, make_key, normalize_query
from dra.providers.search import SearchChain, SearchResult


class FakeSpan:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def set(self, **kwargs):
        return self


class FakeTracer:
    def span(self, *args, **kwargs):
        return FakeSpan()


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str) -> list[SearchResult]:
        self.calls += 1
        return [SearchResult(title="t", url="https://example.com", content=f"c:{query}")]

    def close(self) -> None:
        pass


def test_normalize_query_collapses_whitespace():
    assert normalize_query("  RAG   是什么  ") == "RAG 是什么"


def test_key_is_stable_and_provider_specific():
    assert make_key("tavily", "abc") == make_key("tavily", " abc ")
    assert make_key("tavily", "abc") != make_key("bocha", "abc")


def test_put_then_get_roundtrip(db_path):
    cache = SearchCache(db_path)
    payload = [{"title": "t", "url": "https://e.com", "content": "c", "score": 0.5}]

    cache.put("tavily", "查询", payload)

    assert cache.get("tavily", "查询") == payload


def test_miss_returns_none(db_path):
    cache = SearchCache(db_path)
    assert cache.get("tavily", "从未查过") is None


def test_ttl_expiry(db_path):
    cache = SearchCache(db_path, ttl_days=1)
    cache.put("tavily", "旧查询", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])
    # 直接把创建时间改到 3 天前
    cache.conn.execute(
        "UPDATE search_cache SET created_at=? WHERE provider='tavily'", (time.time() - 3 * 86400,)
    )
    cache.conn.commit()

    assert cache.get("tavily", "旧查询") is None


def test_ttl_zero_means_never_expire(db_path):
    cache = SearchCache(db_path, ttl_days=0)
    cache.put("tavily", "查询", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])
    cache.conn.execute("UPDATE search_cache SET created_at=0")
    cache.conn.commit()

    assert cache.get("tavily", "查询") is not None


def test_stats_count_hits_and_misses(db_path):
    cache = SearchCache(db_path)
    cache.put("tavily", "查询", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])

    cache.get("tavily", "查询")
    cache.get("tavily", "未知")

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_chain_uses_cache_and_skips_provider(db_path):
    cache = SearchCache(db_path)
    provider = FakeProvider()
    chain = SearchChain([provider], cache=cache)
    tracer = FakeTracer()

    first = chain.search("同一个问题", tracer)
    second = chain.search("同一个问题", tracer)

    assert provider.calls == 1, "第二次应命中缓存，不再调用 provider"
    assert [r.url for r in first] == [r.url for r in second]


def test_chain_without_cache_always_calls(db_path):
    provider = FakeProvider()
    chain = SearchChain([provider], cache=None)

    chain.search("q", FakeTracer())
    chain.search("q", FakeTracer())

    assert provider.calls == 2


def test_fuzzy_match_hits_similar_query(db_path):
    cache = SearchCache(db_path)
    payload = [{"title": "t", "url": "https://e.com", "content": "c", "score": 0.0}]
    cache.put("tavily", "各索引类型的内存占用与构建成本有何差异", payload)

    # 措辞略有不同，但 bigram 相似度足够高
    hit = cache.get("tavily", "各索引类型的内存与构建成本差异")

    assert hit == payload
    assert cache.fuzzy_hits == 1


def test_fuzzy_match_rejects_dissimilar_query(db_path):
    cache = SearchCache(db_path)
    cache.put("tavily", "向量数据库的索引类型", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])

    assert cache.get("tavily", "大模型训练需要多少张显卡") is None
    assert cache.misses == 1


def test_similarity_threshold_is_configurable(db_path):
    cache = SearchCache(db_path, similarity_threshold=1.01)
    cache.put("tavily", "各索引类型的内存占用与构建成本有何差异", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])

    # 阈值 > 1 时任何近似匹配都不成立
    assert cache.get("tavily", "各索引类型的内存与构建成本差异") is None


def test_stats_report_fuzzy_hits(db_path):
    cache = SearchCache(db_path)
    cache.put("tavily", "各索引类型的内存占用与构建成本有何差异", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])
    cache.get("tavily", "各索引类型的内存与构建成本差异")

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["fuzzy_hits"] == 1


def test_antonym_queries_do_not_share_cache(db_path):
    cache = SearchCache(db_path)
    cache.put("tavily", "RAG 相比微调的优势", [{"title": "t", "url": "u", "content": "c", "score": 0.0}])

    assert cache.get("tavily", "RAG 相比微调的劣势") is None
