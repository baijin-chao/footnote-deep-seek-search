"""引用校验：判断报告里的断言能否在它所引用的证据中找到支撑。

V1 用词面重叠（lexical grounding）做粗校验，不引入额外的模型调用：
- 中文按字符 bigram，英文按词，去重后计算断言 token 在证据中的覆盖率
- 覆盖率 >= strong 记为 supported，>= weak 记为 weak，否则 unverified
- 引用编号不存在于证据集时记为 missing

为什么分三级而不是二元判断：中文报告大量是"改写+综合"，严格阈值会误杀，
宽松阈值又失去筛选意义。分级既保留了信号，也方便人快速定位可疑处。

已知局限（README 会写明）：
- 只认字面重合，跨语言或大幅改写时可能误判
- 无法识别语义矛盾（数字被篡改但用词相同）
V2 会加模型校验作为补充，而不是替换。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

MARKER_RE = re.compile(r"\[E(\d+)\]")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])|(?<=\n)")

SUPPORTED = "supported"
WEAK = "weak"
UNVERIFIED = "unverified"
MISSING = "missing"

DEFAULT_STRONG = 0.5
DEFAULT_WEAK = 0.3
EPS = 1e-9


@dataclass
class Claim:
    sentence: str
    markers: list[int]
    score: float
    status: str
    detail: str = ""

    @property
    def marker_text(self) -> str:
        return "".join(f"[E{m}]" for m in self.markers)


@dataclass
class VerifyReport:
    claims: list[Claim] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.claims)

    @property
    def supported(self) -> int:
        return sum(1 for c in self.claims if c.status == SUPPORTED)

    @property
    def weak(self) -> int:
        return sum(1 for c in self.claims if c.status == WEAK)

    @property
    def unverified(self) -> int:
        return sum(1 for c in self.claims if c.status == UNVERIFIED)

    @property
    def missing(self) -> int:
        return sum(1 for c in self.claims if c.status == MISSING)

    @property
    def pass_rate(self) -> float:
        """强支撑占比。"""
        return self.supported / self.total if self.total else 1.0

    @property
    def grounded_rate(self) -> float:
        """强支撑 + 弱支撑占比。"""
        return (self.supported + self.weak) / self.total if self.total else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "supported": self.supported,
            "weak": self.weak,
            "unverified": self.unverified,
            "missing": self.missing,
            "pass_rate": round(self.pass_rate, 3),
            "grounded_rate": round(self.grounded_rate, 3),
        }


def tokenize(text: str) -> set[str]:
    """中文取字符 bigram，英文取小写词。"""
    cleaned = MARKER_RE.sub(" ", text or "")
    latin = re.findall(r"[a-z][a-z0-9_\-]{1,}", cleaned.lower())
    cjk = re.findall(r"[\u4e00-\u9fff]", cleaned)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return set(latin) | set(bigrams)


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_SPLIT.split(text or "")]
    return [p for p in parts if p]


def _evidence_tokens(rows: Sequence[Any]) -> dict[int, set[str]]:
    """按 1-based 编号缓存每条证据的 token 集合。"""
    cache: dict[int, set[str]] = {}
    for idx, row in enumerate(rows, start=1):
        body = f"{row['title'] or ''} {row['content'] or ''} {row['snippet'] or ''}"
        cache[idx] = tokenize(body)
    return cache


def verify_citations(
    markdown: str,
    rows: Sequence[Any],
    strong: float = DEFAULT_STRONG,
    weak: float = DEFAULT_WEAK,
) -> VerifyReport:
    """校验 Markdown 中每处 [En] 引用是否有字面支撑。"""
    evidence_tokens = _evidence_tokens(rows)
    report = VerifyReport()

    for sentence in split_sentences(markdown):
        markers = [int(m) for m in MARKER_RE.findall(sentence)]
        if not markers:
            continue

        sent_tokens = tokenize(sentence)
        if not sent_tokens:
            continue

        best = 0.0
        missing = []
        for marker in markers:
            ev = evidence_tokens.get(marker)
            if ev is None:
                missing.append(marker)
                continue
            score = len(sent_tokens & ev) / len(sent_tokens)
            best = max(best, score)

        best = round(best, 4)
        if best == 0.0 and missing:
            status = MISSING
            detail = "引用编号不存在：" + "、".join(f"E{m}" for m in missing)
        elif best + EPS >= strong:
            status = SUPPORTED
            detail = f"字面覆盖率 {best:.0%}"
        elif best + EPS >= weak:
            status = WEAK
            detail = f"字面覆盖率 {best:.0%}，为改写或综合表述"
        else:
            status = UNVERIFIED
            detail = f"字面覆盖率仅 {best:.0%}，低于 {weak:.0%}"

        report.claims.append(
            Claim(sentence=sentence, markers=markers, score=best, status=status, detail=detail)
        )

    return report


def render_references(rows: Sequence[Any], used: set[int]) -> str:
    """程序生成参考来源，只列正文真正引用到的条目。"""
    lines = ["## 参考来源", ""]
    any_item = False
    for idx, row in enumerate(rows, start=1):
        if used and idx not in used:
            continue
        any_item = True
        title = (row["title"] or "").strip() or "无标题"
        url = (row["url"] or "").strip()
        lines.append(f"- **[E{idx}]** {title} — <{url}>")
    if not any_item:
        lines.append("- 无（本次未产生可引用的证据）")
    return "\n".join(lines)


def render_verification_block(
    report: VerifyReport,
    strong: float = DEFAULT_STRONG,
    weak: float = DEFAULT_WEAK,
) -> str:
    """在报告末尾追加校验说明（Markdown 引用块）。"""
    if report.total == 0:
        return "> 引用校验：正文未出现引用标记。"

    head = (
        f"> **引用校验**：共 {report.total} 处引用断言 — "
        f"强支撑 {report.supported} 处（≥{strong:.0%}）、"
        f"弱支撑 {report.weak} 处（{weak:.0%}–{strong:.0%}）、"
        f"未证实 {report.unverified} 处"
    )
    if report.missing:
        head += f"、编号缺失 {report.missing} 处"
    head += "。"

    lines = [
        head,
        ">",
        "> 校验方式为词面覆盖率比对（中文按字符二元组）。它只能排除「引用与原文毫无重合」的情况，"
        "不能证明语义一致；弱支撑多为改写或综合表述，需人工复核。",
    ]

    bad = [c for c in report.claims if c.status in (UNVERIFIED, MISSING)]
    if bad:
        lines.append(">")
        lines.append("> **未证实条目**：")
        for claim in bad[:5]:
            snippet = claim.sentence.strip()
            if len(snippet) > 80:
                snippet = snippet[:80] + "…"
            lines.append(f"> - `{claim.marker_text}` {snippet}（{claim.detail}）")
    return "\n".join(lines)


def strip_reference_section(markdown: str) -> str:
    """去掉模型自己写的参考来源，避免与程序生成的重复。"""
    for heading in ("## 参考来源", "## 参考资料", "### 参考来源", "### 参考资料"):
        pos = markdown.rfind(heading)
        if pos != -1:
            return markdown[:pos].rstrip()
    return markdown.rstrip()
