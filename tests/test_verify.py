"""引用校验的离线测试（不调用任何外部 API）。"""

from __future__ import annotations

import pytest

from dra.verify import (
    MISSING,
    SUPPORTED,
    UNVERIFIED,
    WEAK,
    render_references,
    render_verification_block,
    strip_reference_section,
    tokenize,
    verify_citations,
)


def make_rows(*contents: str):
    return [
        {"title": f"文档{i}", "url": f"https://example.com/{i}", "content": c, "snippet": c[:100]}
        for i, c in enumerate(contents, start=1)
    ]


def test_tokenize_chinese_uses_bigrams():
    tokens = tokenize("检索增强生成")
    assert "检索" in tokens and "索增" in tokens and "生成" in tokens


def test_tokenize_strips_markers():
    assert "E1" not in tokenize("这是结论 [E1]")


def test_supported_when_sentence_overlaps_evidence():
    rows = make_rows("检索增强生成通过外部知识库检索相关文档，再把结果注入上下文来生成回答。")
    markdown = "检索增强生成会把检索到的文档注入上下文来生成回答 [E1]。"

    report = verify_citations(markdown, rows)

    assert report.total == 1
    assert report.claims[0].status == SUPPORTED
    assert report.pass_rate == 1.0


def test_unverified_when_evidence_is_unrelated():
    rows = make_rows("本文讨论的是操作系统调度算法与进程切换开销。")
    markdown = "该模型在金融风控领域的准确率达到 97% [E1]。"

    report = verify_citations(markdown, rows)

    assert report.claims[0].status == UNVERIFIED
    assert report.unverified == 1


def test_missing_when_marker_not_in_evidence():
    rows = make_rows("任意内容")
    markdown = "这是一个没有来源的说法 [E9]。"

    report = verify_citations(markdown, rows)

    assert report.claims[0].status == MISSING
    assert report.missing == 1


def test_sentences_without_markers_are_ignored():
    rows = make_rows("内容")
    report = verify_citations("这段没有引用。这段也没有。", rows)
    assert report.total == 0


def test_multiple_markers_take_best_score():
    rows = make_rows("无关内容", "检索增强生成把文档注入上下文。")
    markdown = "检索增强生成会把文档注入上下文 [E1][E2]。"

    report = verify_citations(markdown, rows)

    assert report.claims[0].status == SUPPORTED
    assert report.claims[0].markers == [1, 2]


def test_threshold_is_configurable():
    rows = make_rows("检索增强生成把文档注入上下文")
    markdown = "检索到的文档数量达到一百万 [E1]。"

    assert verify_citations(markdown, rows, strong=0.9).claims[0].status != SUPPORTED


def test_weak_tier_between_thresholds():
    rows = make_rows("检索增强生成把文档注入上下文")
    markdown = "检索增强生成在金融风控领域效果显著 [E1]。"

    report = verify_citations(markdown, rows, strong=0.99, weak=0.01)

    assert report.claims[0].status == WEAK
    assert report.weak == 1
    assert report.grounded_rate == 1.0


def test_render_references_only_lists_used():
    rows = make_rows("a", "b", "c")
    text = render_references(rows, {1, 3})

    assert "[E1]" in text and "[E3]" in text
    assert "[E2]" not in text


def test_strip_reference_section():
    markdown = "## 正文\n\n结论 [E1]。\n\n## 参考来源\n\n- [E1] 假的"
    stripped = strip_reference_section(markdown)

    assert "参考来源" not in stripped
    assert stripped.endswith("结论 [E1]。")


def test_verification_block_mentions_failures():
    rows = make_rows("本文讨论操作系统调度算法。")
    report = verify_citations("模型准确率 97% [E1]。", rows)

    block = render_verification_block(report)

    assert "未证实" in block
