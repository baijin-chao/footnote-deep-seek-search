"""评测跑批：串行执行、断点续跑、预算兜底。

为什么先不做并发：并发写同一个 SQLite 需要额外处理锁竞争，而搜索缓存已经大幅
降低了额度消耗，串行的稳定性收益更高。并发留到 V2.1，届时改用独立数据库文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agent.machine import ResearchAgent
from ..config import Settings
from ..providers.llm import LLMClient
from .dataset import Question, load_dataset
from .judge import judge_report
from .metrics import QuestionResult, evaluate, summarize
from .report import write_summary


@dataclass
class EvalOptions:
    dataset: Path
    out_dir: Path
    limit: int = 0
    tag: str = ""
    max_cny: float = 0.0
    resume: bool = False
    quiet: bool = False


def _load_done(results_path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not results_path.exists():
        return done
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        done[str(item.get("id"))] = item
    return done


def _append_result(results_path: Path, result: QuestionResult) -> None:
    with results_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.as_dict(), ensure_ascii=False) + "\n")


def _restore(item: dict[str, Any]) -> QuestionResult:
    return QuestionResult(
        id=item["id"],
        category=item["category"],
        difficulty=item.get("difficulty", "medium"),
        status=item.get("status", "unknown"),
        passed=bool(item.get("passed")),
        coverage=float(item.get("coverage", 0.0)),
        covered_items=int(item.get("covered_items", 0)),
        total_items=int(item.get("total_items", 0)),
        grounded_rate=float(item.get("grounded_rate", 0.0)),
        steps=int(item.get("steps", 0)),
        cost_cny=float(item.get("cost_cny", 0.0)),
        elapsed_s=float(item.get("elapsed_s", 0.0)),
        failure=item.get("failure"),
        refused=bool(item.get("refused")),
        factual_errors=list(item.get("factual_errors") or []),
        report_path=str(item.get("report", "")),
        trace_path=str(item.get("trace", "")),
        error=str(item.get("error", "")),
    )


def run_eval(settings: Settings, options: EvalOptions) -> Path:
    questions = load_dataset(options.dataset)
    if options.limit:
        questions = questions[: options.limit]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{options.tag}" if options.tag else stamp
    out_dir = options.out_dir / name
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    done = _load_done(results_path) if options.resume else {}
    results: list[QuestionResult] = [_restore(v) for v in done.values()]
    spent = sum(r.cost_cny for r in results)

    judge_llm = LLMClient(settings)  # judge 不写 trace，避免污染主链路
    try:
        for index, question in enumerate(questions, start=1):
            if question.id in done:
                continue
            if options.max_cny and spent >= options.max_cny:
                if not options.quiet:
                    print(f"⚠ 达到成本上限 ¥{options.max_cny}，提前结束")
                break

            result = _run_one(settings, question, judge_llm, out_dir)
            results.append(result)
            _append_result(results_path, result)
            spent += result.cost_cny

            if not options.quiet:
                mark = "✅" if result.passed else "❌"
                reason = f" ← {result.failure}" if result.failure else ""
                print(
                    f"[{index:>2}/{len(questions)}] {question.id:<12} {mark} "
                    f"覆盖 {result.coverage:.0%}  落地 {result.grounded_rate:.0%}  "
                    f"¥{result.cost_cny}  {result.elapsed_s}s{reason}"
                )
    finally:
        judge_llm.close()

    summary = summarize(results)
    meta = {
        "dataset": str(options.dataset),
        "model": settings.llm_model,
        "tag": options.tag or "-",
    }
    summary_path = write_summary(out_dir, summary, results, meta)

    if not options.quiet:
        print()
        print(f"成功率 {summary['success_rate']:.0%}（{summary['passed']}/{summary['total']}）")
        print(f"总成本 ¥{summary['total_cost_cny']}  延迟 P50 {summary['p50_elapsed_s']}s / P95 {summary['p95_elapsed_s']}s")
        if summary.get("failures"):
            detail = "、".join(f"{k}×{v}" for k, v in summary["failures"].items())
            print(f"失败归因：{detail}")
        print(f"报告：{summary_path}")

    return summary_path


def _run_one(settings: Settings, question: Question, judge_llm: LLMClient, out_dir: Path) -> QuestionResult:
    agent = ResearchAgent(settings)
    run = agent.run(question.question)

    report_text = run.get("report") or ""
    report_path = out_dir / "reports" / f"{question.id}.md"
    if report_text:
        report_path.write_text(report_text, encoding="utf-8")

    judged = judge_report(question, report_text, judge_llm)
    run["report_path"] = str(report_path)
    return evaluate(question, run, judged.as_dict())
