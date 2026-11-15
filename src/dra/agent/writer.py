"""Writer：基于证据生成带引用的报告。"""

from __future__ import annotations

import re
from typing import Any

from ..providers.llm import LLMClient
from ..trace import Tracer
from ..util import truncate
from ..verify import (
    DEFAULT_STRONG,
    DEFAULT_WEAK,
    VerifyReport,
    render_references,
    render_verification_block,
    strip_reference_section,
    verify_citations,
)

SYSTEM = """你是资深研究员，负责基于给定证据撰写中文研究报告。

写作要求：
1. 结构固定：## 摘要 / ## 关键发现 / ## 分析 / ## 结论与局限 / ## 参考来源
2. 每个事实性陈述后面用 [E1]、[E2] 标注来源，编号只能来自给定证据
3. 证据不足以支撑的结论，必须写"现有证据不足以判断"，严禁编造数据、时间、机构
4. 不要罗列证据，要综合、对比、给出判断
5. 600-900 字，Markdown 格式
"""


def build_evidence_block(rows: list[Any], per_item: int = 1200) -> str:
    parts = []
    for idx, row in enumerate(rows, start=1):
        parts.append(
            f"[E{idx}] {row['title'] or '无标题'}（{row['domain']}）\n"
            f"URL: {row['url']}\n"
            f"内容: {truncate(row['content'] or row['snippet'] or '', per_item)}"
        )
    return "\n\n".join(parts)


def write_report(
    question: str,
    rows: list[Any],
    llm: LLMClient,
    tracer: Tracer,
    *,
    note: str = "",
    strong: float = DEFAULT_STRONG,
    weak: float = DEFAULT_WEAK,
) -> tuple[str, list[dict[str, Any]], VerifyReport]:
    evidence_block = build_evidence_block(rows)
    user = f"研究问题：{question}\n\n可用证据：\n{evidence_block}\n"
    if note:
        user += f"\n补充说明：{note}\n"
    user += "\n注意：只写正文，不要输出「参考来源」章节，引用列表由程序生成。"

    with tracer.span("write", kind="step", evidence_count=len(rows)) as span:
        result = llm.complete(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            span_name="write_llm",
            max_tokens=3000,
        )
        body = strip_reference_section(result.text)
        citations = extract_citations(body, rows)
        used = {int(c["marker"][1:]) for c in citations}
        verification = verify_citations(body, rows, strong=strong, weak=weak)

        markdown = "\n\n".join(
            [
                body,
                render_references(rows, used),
                render_verification_block(verification, strong=strong, weak=weak),
            ]
        )
        span.set(
            chars=len(markdown),
            citation_count=len(citations),
            verify_pass_rate=verification.pass_rate,
            verify_grounded_rate=verification.grounded_rate,
            verify_total=verification.total,
        )
        return markdown, citations, verification


def extract_citations(markdown: str, rows: list[Any]) -> list[dict[str, Any]]:
    used = {int(m) for m in re.findall(r"\[E(\d+)\]", markdown)}
    out = []
    for idx in sorted(used):
        if 1 <= idx <= len(rows):
            row = rows[idx - 1]
            out.append({"marker": f"E{idx}", "url": row["url"], "title": row["title"], "evidence_id": row["id"]})
    return out
