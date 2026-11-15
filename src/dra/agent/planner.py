"""Planner：把用户问题拆成互补子问题。"""

from __future__ import annotations

import re
from pydantic import BaseModel, Field

from ..providers.llm import LLMClient
from ..trace import Tracer

SYSTEM = """你是研究规划助手。用户会给你一个开放性问题，你需要把它拆成 3-6 个互补的子问题。

要求：
1. 子问题之间角度不同（如：定义与背景、关键数据、对比、原因机制、风险与争议）
2. 每个子问题都能独立拿去搜索，不要写"分析一下"这种空泛表述
3. 中文，每条不超过 30 字
4. 只输出 JSON，格式：{"questions": ["子问题1", "子问题2"]}
"""


class Plan(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=8)


def make_plan(question: str, llm: LLMClient, tracer: Tracer, max_items: int = 6) -> list[str]:
    with tracer.span("plan", kind="step", question=question) as span:
        plan, _ = llm.complete_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
            Plan,
            span_name="plan_llm",
        )
        cleaned: list[str] = []
        seen: set[str] = set()
        for q in plan.questions:
            q = re.sub(r"^\s*[\d一二三四五六*\-\.、]+[\.\)、]?\s*", "", str(q)).strip()
            if not q or len(q) > 80:
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(q)
        span.set(sub_questions=cleaned)
        return cleaned[:max_items]
