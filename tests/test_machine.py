"""状态机的离线测试。

用桩替换 LLM / 搜索 / 抓取，验证状态转移、预算中断、失败路径。
这是项目核心逻辑，不允许没有覆盖。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dra.agent import machine
from dra.config import Settings
from dra.providers.fetch import Page
from dra.providers.search import SearchResult


class StubLLM:
    """按调用类型返回预设结果，并模拟 token 消耗。"""

    plan_questions: list[str] = ["RAG 的流程是什么", "RAG 的局限有哪些"]

    def __init__(self, settings, tracer=None, on_usage=None):
        self.on_usage = on_usage

    def complete_json(self, messages, schema, **kwargs):
        if self.on_usage:
            self.on_usage(120, 40, 0.001)
        return schema(questions=self.plan_questions), SimpleNamespace(text="")

    def complete(self, messages, **kwargs):
        if self.on_usage:
            self.on_usage(300, 120, 0.002)
        return SimpleNamespace(text="## 摘要\n\nRAG 先检索再生成 [E1]。\n\n## 结论\n\n证据有限 [E1]。")

    def close(self):
        pass


class StubSearch:
    def __init__(self, results):
        self.results = results

    def search(self, query, tracer):
        if isinstance(self.results, Exception):
            raise self.results
        return list(self.results)

    def close(self):
        pass


class StubFetcher:
    def __init__(self, settings=None):
        pass

    def fetch(self, url, tracer=None):
        return Page(
            url=url,
            final_url=url,
            status=200,
            title=f"文档 {url}",
            text="检索增强生成通过外部知识库检索文档，再把结果注入上下文生成回答。" * 3,
        )

    def close(self):
        pass


def default_results():
    return [
        SearchResult(title="文档A", url="https://example.com/a", content="RAG 的流程是索引、检索、生成"),
        SearchResult(title="文档B", url="https://example.com/b", content="RAG 的局限包括检索质量依赖"),
    ]


@pytest.fixture
def build_agent(work_dir, monkeypatch):
    """构造一个外部依赖全部打桩的 agent。"""

    def build(results=None, llm_cls=StubLLM, **overrides):
        settings = replace(
            Settings(
                llm_api_key="test-key",
                search_api_key="test-key",
                db_path=work_dir / "dra.db",
                trace_dir=work_dir / "traces",
            ),
            **overrides,
        ) if overrides else Settings(
            llm_api_key="test-key",
            search_api_key="test-key",
            db_path=work_dir / "dra.db",
            trace_dir=work_dir / "traces",
        )
        payload = default_results() if results is None else results
        monkeypatch.setattr(machine, "LLMClient", llm_cls)
        monkeypatch.setattr(machine, "Fetcher", StubFetcher)
        monkeypatch.setattr(machine, "build_search", lambda s, cache=None: StubSearch(payload))
        return machine.ResearchAgent(settings)

    return build


def collect_events(agent):
    events = []
    agent.emit = lambda event, data: events.append((event, data))
    return events


def test_happy_path_reaches_done(build_agent):
    agent = build_agent()
    events = collect_events(agent)

    result = agent.run("RAG 是什么")

    states = [data["state"] for event, data in events if event == "state"]
    assert states == ["PLAN", "GATHER", "REFLECT", "WRITE"]
    assert result["status"] == "done"
    assert result["stats"]["evidence"] > 0
    assert result["report"].strip()
    assert result["verification"]["total"] > 0


def test_plan_event_carries_sub_questions(build_agent):
    agent = build_agent()
    events = collect_events(agent)

    agent.run("RAG 是什么")

    plan = [data for event, data in events if event == "plan"]
    assert len(plan) == 1
    assert len(plan[0]["questions"]) == 2


def test_claims_are_persisted(build_agent):
    agent = build_agent()

    result = agent.run("RAG 是什么")

    claims = agent.store.list_claims(result["run_id"])
    assert claims, "带引用的断言应写入 claim 表"
    assert {c["support"] for c in claims} <= {"supported", "weak", "unverified", "missing"}


def test_budget_stops_gathering_early(build_agent):
    # 步数上限 2：允许「规划 1 步 + 1 个子问题」，第二个子问题前被预算拦下
    agent = build_agent(budget_max_steps=2)
    events = collect_events(agent)

    result = agent.run("RAG 是什么")

    assert result["stop_reason"], "预算中断必须给出原因"
    assert result["status"] in ("done", "budget_exceeded")
    assert result["report"].strip(), "预算中断也要输出已有结论"
    assert any(event == "reflect" for event, _ in events)
    gathered = [data for event, data in events if event == "search"]
    assert len(gathered) == 1, "只应抓取第一个子问题"


def test_no_evidence_fails_cleanly(build_agent):
    agent = build_agent(results=[])
    events = collect_events(agent)

    result = agent.run("一个搜不到的问题")

    assert result["status"] == "failed"
    assert "证据" in (result["stop_reason"] or "")
    assert result["report"] == ""
    assert any(event == "reflect" for event, _ in events)


def test_search_exception_marks_subq_failed(build_agent):
    agent = build_agent(results=RuntimeError("搜索服务不可用"))
    events = collect_events(agent)

    result = agent.run("RAG 是什么")

    assert result["status"] == "failed"
    failed = [data for event, data in events if event == "subq_failed"]
    assert failed and "搜索服务不可用" in failed[0]["error"]


def test_zero_sub_questions_is_handled(build_agent):
    class EmptyPlanLLM(StubLLM):
        plan_questions: list[str] = []

    agent = build_agent(llm_cls=EmptyPlanLLM)
    events = collect_events(agent)

    result = agent.run("RAG 是什么")

    assert result["status"] == "failed"
    assert any(event == "error" for event, _ in events)


def test_trace_file_is_written(build_agent):
    agent = build_agent()

    result = agent.run("RAG 是什么")

    trace = Path(result["trace"])
    assert trace.exists()
    assert '"name": "plan"' in trace.read_text(encoding="utf-8")
