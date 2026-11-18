"""录制回放的离线测试（不联网）。"""

from __future__ import annotations

import pytest

from dra.config import Settings
from dra.providers.fetch import Fetcher
from dra.recording import Recorder, RecordingError, make_key
from dra.providers.search import SearchResult, TavilySearch


def make_settings(work_dir, **overrides) -> Settings:
    from dataclasses import replace

    base = Settings(
        llm_api_key="k",
        search_api_key="k",
        fixtures_dir=work_dir / "fixtures",
        db_path=work_dir / "dra.db",
        trace_dir=work_dir / "traces",
    )
    return replace(base, **overrides) if overrides else base


def test_key_is_stable_for_same_input():
    assert make_key("llm", "a", 1) == make_key("llm", "a", 1)
    assert make_key("llm", "a", 1) != make_key("llm", "a", 2)


def test_recorder_roundtrip(work_dir):
    rec = Recorder("record", work_dir / "fixtures")
    rec.save("fetch", "abc", {"text": "正文"})

    rec_mock = Recorder("mock", work_dir / "fixtures")
    assert rec_mock.load("fetch", "abc")["payload"]["text"] == "正文"


def test_mock_mode_raises_when_recording_missing(work_dir):
    rec = Recorder("mock", work_dir / "fixtures")

    with pytest.raises(RecordingError) as exc:
        rec.require("fetch", "missing", hint="url=https://example.com")

    assert "RUN_MODE=record" in str(exc.value)


def test_fetcher_mock_does_not_hit_network(work_dir, monkeypatch):
    url = "https://example.com/a"
    Recorder("record", work_dir / "fixtures").save(
        "fetch", make_key("fetch", url), {"url": url, "final_url": url, "status": 200, "title": "T", "text": "正文内容"}
    )

    settings = make_settings(work_dir, run_mode="mock")
    fetcher = Fetcher(settings)

    def explode(*args, **kwargs):
        raise AssertionError("mock 模式不应发起网络请求")

    monkeypatch.setattr(fetcher._http, "get", explode)

    page = fetcher.fetch(url)

    assert page.text == "正文内容"
    assert page.title == "T"


def test_search_mock_returns_recorded_results(work_dir, monkeypatch):
    query = "RAG 是什么"
    Recorder("record", work_dir / "fixtures").save(
        "search",
        make_key("search", "tavily", query),
        {"results": [{"title": "T", "url": "https://e.com", "content": "C", "score": 0.5}]},
    )

    settings = make_settings(work_dir, run_mode="mock")
    provider = TavilySearch(settings)

    def explode(*args, **kwargs):
        raise AssertionError("mock 模式不应发起网络请求")

    monkeypatch.setattr(provider._http, "post", explode)

    results = provider.search(query)

    assert results == [SearchResult(title="T", url="https://e.com", content="C", score=0.5)]
