"""评测指标：单题判定、失败归因、汇总统计。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .dataset import Question

# 失败类别（顺序即优先级）
FAILURES = (
    "crash",
    "no_evidence",
    "fetch_blocked",
    "budget_exceeded",
    "weak_grounding",
    "fabricated",
    "uncovered",
    "refusal_missing",
)

FAILURE_LABELS = {
    "crash": "运行崩溃",
    "no_evidence": "无有效证据",
    "fetch_blocked": "抓取失败",
    "budget_exceeded": "预算耗尽",
    "weak_grounding": "引用落地率低",
    "fabricated": "存在编造",
    "uncovered": "要点未覆盖",
    "refusal_missing": "该拒答未拒答",
}


@dataclass
class QuestionResult:
    id: str
    category: str
    difficulty: str
    status: str
    passed: bool
    coverage: float
    covered_items: int
    total_items: int
    grounded_rate: float
    steps: int
    cost_cny: float
    elapsed_s: float
    failure: str | None = None
    refused: bool = False
    factual_errors: list[str] = field(default_factory=list)
    report_path: str = ""
    trace_path: str = ""
    error: str = ""
    # 判定所用的原始信号，保留下来供重判分（rejudge）复用，避免重跑 agent
    signals: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "difficulty": self.difficulty,
            "status": self.status,
            "passed": self.passed,
            "coverage": round(self.coverage, 3),
            "covered_items": self.covered_items,
            "total_items": self.total_items,
            "grounded_rate": round(self.grounded_rate, 3),
            "steps": self.steps,
            "cost_cny": round(self.cost_cny, 4),
            "elapsed_s": round(self.elapsed_s, 1),
            "failure": self.failure,
            "refused": self.refused,
            "factual_errors": self.factual_errors,
            "report": self.report_path,
            "trace": self.trace_path,
            "error": self.error,
            "signals": self.signals,
        }


def classify_failure(question: Question, signals: dict[str, Any]) -> str | None:
    """按优先级归因。返回 None 表示不算失败。

    无解题单独判定：它的「通过」取决于是否拒答，而不是要点覆盖率。
    """
    if signals.get("error"):
        return "crash"
    if signals.get("status") not in ("done", "budget_exceeded"):
        return "crash"
    if signals.get("evidence", 0) == 0:
        return "no_evidence"

    attempts = max(1, signals.get("fetch_attempts", 0))
    documents = signals.get("documents", 0)
    # 抓取失败要同时满足「成功率低」和「证据本来就少」，
    # 否则会把「抓了很多、失败一些、但结论正确」的题误判成抓取失败
    if attempts >= 3 and documents < 3 and documents / attempts < 0.5:
        return "fetch_blocked"

    stop_reason = str(signals.get("stop_reason") or "")
    if "预算" in stop_reason or "上限" in stop_reason or signals.get("status") == "budget_exceeded":
        return "budget_exceeded"

    if question.should_refuse:
        if not signals.get("refused"):
            return "refusal_missing"
        return "fabricated" if signals.get("factual_errors") else None

    if signals.get("grounded_rate", 1.0) < 0.5:
        return "weak_grounding"
    if signals.get("factual_errors"):
        return "fabricated"
    if signals.get("covered_items", 0) < question.pass_threshold:
        return "uncovered"
    return None


def evaluate(question: Question, run: dict[str, Any], judged: dict[str, Any]) -> QuestionResult:
    """把一次 agent 运行 + judge 结果合成一条评测记录。"""
    stats = run.get("stats") or {}
    verification = run.get("verification") or {}
    covered_items = int(judged.get("covered_items", 0))
    total_items = int(judged.get("total_items", len(question.must_cover)))
    coverage = covered_items / total_items if total_items else 0.0
    grounded = float(verification.get("grounded_rate", 0.0))

    signals = {
        "status": run.get("status"),
        "error": run.get("error"),
        "evidence": stats.get("evidence", 0),
        "documents": stats.get("documents", stats.get("evidence", 0)),
        "fetch_attempts": stats.get("fetch_attempts", 0),
        "stop_reason": run.get("stop_reason"),
        "grounded_rate": grounded,
        "covered_items": covered_items,
        "refused": judged.get("refused", False),
        "factual_errors": judged.get("factual_errors", []),
    }

    failure = classify_failure(question, signals)
    return QuestionResult(
        id=question.id,
        category=question.category,
        difficulty=question.difficulty,
        status=str(run.get("status", "unknown")),
        passed=failure is None,
        coverage=coverage,
        covered_items=covered_items,
        total_items=total_items,
        grounded_rate=grounded,
        steps=int(stats.get("steps", 0)),
        cost_cny=float(stats.get("cost_cny", 0.0)),
        elapsed_s=float(stats.get("elapsed_s", 0.0)),
        failure=failure,
        refused=bool(judged.get("refused", False)),
        factual_errors=list(judged.get("factual_errors", [])),
        report_path=str(run.get("report_path", "")),
        trace_path=str(run.get("trace", "")),
        error=str(run.get("error") or ""),
        signals=signals,
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[rank]


def summarize(results: list[QuestionResult]) -> dict[str, Any]:
    """汇总指标。分母是全部题，失败的题同样计入。"""
    total = len(results)
    if total == 0:
        return {"total": 0}

    passed = sum(1 for r in results if r.passed)
    refusals = [r for r in results if r.category == "no_answer"]
    grounded = [r.grounded_rate for r in results if r.grounded_rate > 0]
    elapsed = [r.elapsed_s for r in results]

    by_category: dict[str, dict[str, Any]] = {}
    for cat in sorted({r.category for r in results}):
        subset = [r for r in results if r.category == cat]
        by_category[cat] = {
            "total": len(subset),
            "passed": sum(1 for r in subset if r.passed),
            "rate": round(sum(1 for r in subset if r.passed) / len(subset), 3),
        }

    failures: dict[str, int] = {}
    for r in results:
        if r.failure:
            failures[r.failure] = failures.get(r.failure, 0) + 1

    return {
        "total": total,
        "passed": passed,
        "success_rate": round(passed / total, 3),
        "refusal_total": len(refusals),
        "refusal_correct": sum(1 for r in refusals if r.passed),
        "refusal_rate": round(sum(1 for r in refusals if r.passed) / len(refusals), 3) if refusals else None,
        "avg_grounded_rate": round(sum(grounded) / len(grounded), 3) if grounded else 0.0,
        "avg_steps": round(sum(r.steps for r in results) / total, 1),
        "avg_cost_cny": round(sum(r.cost_cny for r in results) / total, 4),
        "total_cost_cny": round(sum(r.cost_cny for r in results), 4),
        "p50_elapsed_s": round(percentile(elapsed, 50), 1),
        "p95_elapsed_s": round(percentile(elapsed, 95), 1),
        "by_category": by_category,
        "failures": failures,
    }
