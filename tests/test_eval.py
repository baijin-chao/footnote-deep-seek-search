"""评测模块的离线测试（不调用外部模型）。"""

from __future__ import annotations

import json

import pytest

from dra.eval.dataset import DatasetError, Question, load_dataset
from dra.eval.metrics import classify_failure, evaluate, percentile, summarize


def write_dataset(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def make_row(**overrides):
    row = {
        "id": "q1",
        "category": "fact",
        "question": "测试问题",
        "must_cover": ["要点一", "要点二", "要点三"],
        "should_refuse": False,
        "expected_sources": [],
        "difficulty": "easy",
        "notes": "",
    }
    row.update(overrides)
    return row


def test_load_dataset_ok(db_path):
    path = write_dataset(db_path.with_suffix(".jsonl"), [make_row()])
    questions = load_dataset(path)

    assert len(questions) == 1
    assert questions[0].id == "q1"


def test_load_dataset_rejects_duplicate_id(db_path):
    path = write_dataset(db_path.with_suffix(".jsonl"), [make_row(), make_row()])

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_load_dataset_rejects_unknown_category(db_path):
    path = write_dataset(db_path.with_suffix(".jsonl"), [make_row(category="nonsense")])

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_load_dataset_rejects_no_answer_without_refuse_flag(db_path):
    path = write_dataset(db_path.with_suffix(".jsonl"), [make_row(category="no_answer", should_refuse=False)])

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_load_dataset_reports_line_number(db_path):
    path = db_path.with_suffix(".jsonl")
    path.write_text('{"id": "q1"}\n', encoding="utf-8")

    with pytest.raises(DatasetError) as exc:
        load_dataset(path)
    assert "第 1 行" in str(exc.value)


def test_pass_threshold_is_two_thirds():
    assert Question("a", "fact", "q", ("a", "b", "c"), False).pass_threshold == 2
    assert Question("b", "fact", "q", ("a", "b"), False).pass_threshold == 2
    assert Question("c", "fact", "q", ("a", "b", "c", "d"), False).pass_threshold == 3


def test_classify_prioritises_no_evidence():
    q = Question("q", "fact", "问题", ("a", "b", "c"), False)
    signals = {"status": "done", "evidence": 0, "covered_items": 0}
    assert classify_failure(q, signals) == "no_evidence"


def test_classify_budget_before_uncovered():
    q = Question("q", "fact", "问题", ("a", "b", "c"), False)
    signals = {
        "status": "budget_exceeded",
        "evidence": 5,
        "documents": 5,
        "fetch_attempts": 5,
        "grounded_rate": 0.9,
        "covered_items": 0,
        "stop_reason": "成本达到上限 ¥0.6",
    }
    assert classify_failure(q, signals) == "budget_exceeded"


def test_no_answer_question_fails_without_refusal():
    q = Question("q", "no_answer", "问题", ("a", "b"), True)
    signals = {"status": "done", "evidence": 4, "documents": 4, "fetch_attempts": 4, "grounded_rate": 0.8, "refused": False}
    assert classify_failure(q, signals) == "refusal_missing"


def test_no_answer_question_passes_when_refused():
    q = Question("q", "no_answer", "问题", ("a", "b"), True)
    signals = {
        "status": "done",
        "evidence": 4,
        "documents": 4,
        "fetch_attempts": 4,
        "grounded_rate": 0.8,
        "refused": True,
        "factual_errors": [],
    }
    assert classify_failure(q, signals) is None


def test_evaluate_builds_result():
    q = Question("q1", "fact", "问题", ("a", "b", "c"), False)
    run = {"status": "done", "stats": {"evidence": 5, "documents": 5, "fetch_attempts": 5, "steps": 8, "cost_cny": 0.03, "elapsed_s": 20.0}, "verification": {"grounded_rate": 0.9}, "report": "x"}
    judged = {"covered_items": 2, "total_items": 3, "refused": False, "factual_errors": []}

    result = evaluate(q, run, judged)

    assert result.passed is True
    assert result.coverage == pytest.approx(2 / 3, rel=1e-3)


def test_summarize_counts_failures_in_denominator():
    q1 = Question("q1", "fact", "问题", ("a", "b", "c"), False)
    q2 = Question("q2", "fact", "问题", ("a", "b", "c"), False)
    ok = evaluate(q1, {"status": "done", "stats": {"evidence": 3, "documents": 3, "fetch_attempts": 3}, "verification": {"grounded_rate": 0.9}}, {"covered_items": 3, "total_items": 3})
    bad = evaluate(q2, {"status": "done", "stats": {"evidence": 0}}, {"covered_items": 0, "total_items": 3})

    summary = summarize([ok, bad])

    assert summary["total"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["failures"]["no_evidence"] == 1


def test_fetch_blocked_requires_few_documents():
    q = Question("q", "fact", "问题", ("a", "b", "c"), False)
    # 抓取成功率低，但已有 7 篇证据，结论仍可能正确 → 不归为抓取失败
    signals = {
        "status": "done",
        "evidence": 7,
        "documents": 7,
        "fetch_attempts": 18,
        "grounded_rate": 0.9,
        "covered_items": 3,
    }
    assert classify_failure(q, signals) is None


def test_fetch_blocked_when_evidence_is_thin():
    q = Question("q", "fact", "问题", ("a", "b", "c"), False)
    signals = {
        "status": "done",
        "evidence": 1,
        "documents": 1,
        "fetch_attempts": 18,
        "grounded_rate": 0.9,
        "covered_items": 0,
    }
    assert classify_failure(q, signals) == "fetch_blocked"


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 95) == 4
    assert percentile([], 50) == 0


def test_judge_output_accepts_point_alias():
    """模型实际返回过 points/point 而不是 covered/item，必须兼容，否则覆盖率会被算成 0。"""
    from dra.eval.judge import JudgeOutput

    out = JudgeOutput.model_validate(
        {
            "points": [{"point": "要点一", "covered": True, "quote": "原文"}],
            "errors": ["与来源矛盾"],
            "refused": False,
            "notes": "模型爱加的多余字段",
        }
    )

    assert out.covered[0].item == "要点一"
    assert out.covered[0].covered is True
    assert out.factual_errors == ["与来源矛盾"]
