"""状态机：INIT → PLAN → GATHER → REFLECT → WRITE → DONE。

V0 版本：串行执行，REFLECT 只做"有没有证据"的粗判断。
反思回环、并行检索、预算分级留到 V3。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..cache import SearchCache
from ..config import Settings
from ..models import Stats
from ..providers.fetch import Fetcher
from ..providers.llm import LLMClient
from ..providers.search import SearchChain, build_search
from ..store import Store
from ..trace import Tracer
from ..util import now_iso, short_id
from .planner import make_plan
from .reader import Reader
from .writer import write_report

TERMINAL = {"DONE", "FAILED", "BUDGET_EXCEEDED", "CANCELLED"}

Emit = Callable[[str, dict[str, Any]], None]


class ResearchAgent:
    def __init__(self, settings: Settings, emit: Emit | None = None) -> None:
        self.s = settings
        self.emit = emit or (lambda event, data: None)
        self.store = Store(settings.db_path)

    # ------------------------------------------------------------------
    def run(self, question: str, mode: str | None = None) -> dict[str, Any]:
        mode = mode or self.s.run_mode
        run_id = short_id()
        stats = Stats()
        tracer = Tracer(run_id, self.s.trace_dir, self.store)
        llm = LLMClient(self.s, tracer, on_usage=lambda tin, tout, cost: stats.add_llm(tin, tout, cost))
        cache = SearchCache(self.s.db_path, self.s.search_cache_ttl_days) if self.s.search_cache else None
        search: SearchChain = build_search(self.s, cache=cache)
        fetcher = Fetcher(self.s)
        reader = Reader(self.s, fetcher)
        t0 = time.perf_counter()

        self.store.create_run(run_id, question, mode, {"model": self.s.llm_model}, now_iso())
        self._emit("run_started", run_id=run_id, question=question, mode=mode)

        state = "PLAN"
        stop_reason: str | None = None
        report_md = ""
        citations: list[dict[str, Any]] = []
        verification = None
        error: str | None = None

        try:
            while state not in TERMINAL:
                self._emit("state", state=state, steps=stats.steps)
                elapsed = time.perf_counter() - t0

                if state == "PLAN":
                    stop_reason = self._budget_reason(stats, elapsed)
                    if stop_reason:
                        state = "BUDGET_EXCEEDED"
                        break
                    questions = make_plan(question, llm, tracer)
                    if not questions:
                        raise RuntimeError("规划失败：没有产出子问题")
                    for i, text in enumerate(questions):
                        self.store.add_subq(run_id, text, i)
                    stats.steps += 1
                    self._emit("plan", questions=questions)
                    state = "GATHER"

                elif state == "GATHER":
                    pending = [r for r in self.store.list_subqs(run_id) if r["status"] == "pending"]
                    if not pending:
                        state = "REFLECT"
                        continue
                    for row in pending:
                        stop_reason = self._budget_reason(stats, time.perf_counter() - t0)
                        if stop_reason:
                            state = "REFLECT"
                            break
                        try:
                            self._gather_one(run_id, row, search, reader, tracer, stats)
                        except Exception as exc:
                            self.store.set_subq_status(row["id"], "failed")
                            self._emit("subq_failed", question=row["text"], error=str(exc))
                        stats.steps += 1
                    else:
                        state = "REFLECT"

                elif state == "REFLECT":
                    evidence_count = self.store.count_evidence(run_id)
                    self._emit("reflect", evidence_count=evidence_count, stop_reason=stop_reason)
                    if evidence_count == 0:
                        stop_reason = "没有获取到任何有效证据"
                        state = "FAILED"
                        break
                    state = "WRITE"

                elif state == "WRITE":
                    rows = self.store.list_evidence(run_id)
                    note = f"注意：检索在「{stop_reason}」处提前结束，未覆盖全部子问题。" if stop_reason else ""
                    report_md, citations, verification = write_report(
                        question,
                        rows,
                        llm,
                        tracer,
                        note=note,
                        strong=self.s.verify_strong,
                        weak=self.s.verify_weak,
                    )
                    for claim in verification.claims:
                        self.store.add_claim(run_id, claim.sentence, claim.markers, claim.status)
                    self._emit("verify", **verification.as_dict())
                    self.store.save_report(run_id, report_md, citations, now_iso())
                    stats.steps += 1
                    state = "DONE"

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            state = "FAILED"
            self._emit("error", message=error)

        elapsed = time.perf_counter() - t0
        final_status = "done" if state in ("DONE", "BUDGET_EXCEEDED") else "failed"
        if state == "BUDGET_EXCEEDED":
            final_status = "budget_exceeded"

        self.store.finish_run(
            run_id,
            final_status,
            now_iso(),
            stats.tokens_in,
            stats.tokens_out,
            round(stats.cost_cny, 6),
            stats.steps,
            error or stop_reason,
        )

        result = {
            "run_id": run_id,
            "status": final_status,
            "report": report_md,
            "citations": citations,
            "stats": {
                "steps": stats.steps,
                "tokens_in": stats.tokens_in,
                "tokens_out": stats.tokens_out,
                "cost_cny": round(stats.cost_cny, 4),
                "evidence": self.store.count_evidence(run_id),
                "documents": self.store.count_evidence(run_id),
                "fetch_attempts": stats.fetches,
                "elapsed_s": round(elapsed, 1),
            },
            "stop_reason": stop_reason,
            "error": error,
            "verification": verification.as_dict() if verification else None,
            "cache": cache.stats() if cache else None,
            "trace": str(tracer.path),
        }
        self._emit("done", **result)

        try:
            search.close()
            fetcher.close()
            llm.close()
            if cache:
                cache.close()
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    def _gather_one(self, run_id: str, row, search: SearchChain, reader: Reader, tracer: Tracer, stats: Stats) -> None:
        question = row["text"]
        with tracer.span("subq", kind="step", question=question, sub_q_id=row["id"]):
            self._gather_one_inner(run_id, row, search, reader, tracer, stats)

    def _gather_one_inner(self, run_id: str, row, search: SearchChain, reader: Reader, tracer: Tracer, stats: Stats) -> None:
        question = row["text"]
        self.store.set_subq_status(row["id"], "running")
        self._emit("search", question=question)

        results = search.search(question, tracer)
        stats.searches += 1
        self._emit("search_done", question=question, results=len(results))

        docs = reader.read(results, tracer, per_question=3, seen_hashes=self.store.existing_hashes(run_id))
        stats.fetches += len(results[:3])
        for doc in docs:
            self.store.add_evidence(
                run_id=run_id,
                sub_q_id=row["id"],
                url=doc.url,
                title=doc.title,
                domain=doc.domain,
                snippet=doc.snippet,
                content=doc.text,
                content_hash=doc.content_hash,
                credibility=doc.credibility,
                fetched_at=now_iso(),
            )
        self.store.set_subq_status(row["id"], "done" if docs else "skipped")
        self._emit("read_done", question=question, docs=len(docs))

    def _budget_reason(self, stats: Stats, elapsed: float) -> str | None:
        if stats.steps >= self.s.budget_max_steps:
            return f"步数达到上限 {self.s.budget_max_steps}"
        if stats.tokens_in + stats.tokens_out >= self.s.budget_max_tokens:
            return f"token 用量达到上限 {self.s.budget_max_tokens}"
        if stats.cost_cny >= self.s.budget_max_cny:
            return f"成本达到上限 ¥{self.s.budget_max_cny}"
        if elapsed >= self.s.budget_max_seconds:
            return f"耗时达到上限 {self.s.budget_max_seconds:.0f}s"
        return None

    def _emit(self, event: str, **data: Any) -> None:
        self.emit(event, data)
