"""LLM judge：判断报告是否覆盖要点、是否该拒答、是否编造。

judge 只做初筛，必须经过人工校准（见 docs/06-eval-design.md §4.3）才能采信。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..providers.llm import LLMClient
from .dataset import Question

SYSTEM = """你是严格的研究报告评测员。你会拿到一个问题、若干个「必须覆盖的要点」和一份报告。

判定规则：
1. 逐个要点判断报告是否真的覆盖了它，不做善意推测。只有报告明确表达了该含义才算覆盖。
2. 判定覆盖时必须从报告中摘录原文作为依据（quote 字段），摘不出来就不算覆盖。
3. 不要因为报告篇幅长、措辞好就给分，只看要点是否命中。
4. 如果报告包含与事实明显不符、或与所引来源矛盾的断言，写进 factual_errors。
5. 如果报告明确说明「无法获得可靠信息 / 无法给出结论」，把 refused 置为 true。
6. 只输出 JSON，不要解释，不要加额外字段。

输出格式必须严格如下（字段名不可改）：
{"covered": [{"item": "要点原文", "covered": true, "quote": "报告中的原句"}],
 "factual_errors": [],
 "refused": false}
"""


class CoverageItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # 模型常把 item 写成 point，这里做兼容，避免整条判分被丢弃
    item: str = Field(validation_alias=AliasChoices("item", "point", "text", "requirement"))
    covered: bool = False
    quote: str = ""


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    covered: list[CoverageItem] = Field(
        default_factory=list, validation_alias=AliasChoices("covered", "points", "items")
    )
    factual_errors: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("factual_errors", "errors")
    )
    refused: bool = False


@dataclass
class JudgeResult:
    covered_items: int
    total_items: int
    refused: bool
    factual_errors: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "covered_items": self.covered_items,
            "total_items": self.total_items,
            "refused": self.refused,
            "factual_errors": self.factual_errors,
            "details": self.details,
            "error": self.error,
        }


def build_prompt(question: Question, report: str) -> list[dict[str, str]]:
    items = "\n".join(f"{i}. {text}" for i, text in enumerate(question.must_cover, start=1))
    user = (
        f"## 问题\n{question.question}\n\n"
        f"## 必须覆盖的要点\n{items}\n\n"
        f"## 判分说明\n{question.notes or '无'}\n\n"
        f"## 报告\n{report}\n\n"
        "请按 system 的要求输出 JSON。"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def judge_report(question: Question, report: str, llm: LLMClient) -> JudgeResult:
    total = len(question.must_cover)
    if not report.strip():
        return JudgeResult(covered_items=0, total_items=total, refused=False, error="报告为空")

    try:
        output, _ = llm.complete_json(
            build_prompt(question, report), JudgeOutput, span_name="judge", temperature=0.0
        )
    except Exception as exc:  # judge 失败不阻断评测流程，标记后继续
        return JudgeResult(covered_items=0, total_items=total, refused=False, error=str(exc))

    covered = sum(1 for item in output.covered if item.covered)
    # judge 可能漏判或多项，按 must_cover 条数上限收口，避免覆盖率超过 100%
    covered = min(covered, total)
    return JudgeResult(
        covered_items=covered,
        total_items=total,
        refused=bool(output.refused),
        factual_errors=list(output.factual_errors),
        details=[item.model_dump() for item in output.covered],
    )
