"""评测报告：把结果写成 summary.md 与 summary.csv。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .metrics import FAILURE_LABELS, QuestionResult

CATEGORY_LABELS = {
    "fact": "事实型",
    "compare": "对比型",
    "fresh": "时效型",
    "multi_hop": "多跳",
    "no_answer": "无解",
}


def write_csv(path: Path, results: list[QuestionResult]) -> None:
    fields = [
        "id",
        "category",
        "difficulty",
        "passed",
        "failure",
        "coverage",
        "grounded_rate",
        "steps",
        "cost_cny",
        "elapsed_s",
        "refused",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in results:
            row = r.as_dict()
            writer.writerow({k: row[k] for k in fields})


def render_markdown(summary: dict[str, Any], results: list[QuestionResult], meta: dict[str, Any]) -> str:
    lines: list[str] = ["# 评测报告", ""]

    lines.append(f"- 数据集：`{meta.get('dataset', '')}`")
    lines.append(f"- 模型：`{meta.get('model', '')}`")
    lines.append(f"- 标签：`{meta.get('tag', '')}`")
    lines.append(f"- 题数：{summary.get('total', 0)}")
    lines.append("")

    lines.append("## 总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 任务成功率 | {summary.get('success_rate', 0):.0%}（{summary.get('passed', 0)}/{summary.get('total', 0)}） |")
    refusal_rate = summary.get("refusal_rate")
    if refusal_rate is not None:
        lines.append(f"| 拒答正确率 | {refusal_rate:.0%}（{summary.get('refusal_correct', 0)}/{summary.get('refusal_total', 0)}） |")
    lines.append(f"| 平均引用落地率 | {summary.get('avg_grounded_rate', 0):.0%} |")
    lines.append(f"| 平均步数 | {summary.get('avg_steps', 0)} |")
    lines.append(f"| 单题成本 | ¥{summary.get('avg_cost_cny', 0)} |")
    lines.append(f"| 总成本 | ¥{summary.get('total_cost_cny', 0)} |")
    lines.append(f"| 延迟 P50 / P95 | {summary.get('p50_elapsed_s', 0)}s / {summary.get('p95_elapsed_s', 0)}s |")
    lines.append("")

    lines.append("## 分类别")
    lines.append("")
    lines.append("| 类别 | 通过 / 总数 | 通过率 |")
    lines.append("|---|---|---|")
    for cat, data in (summary.get("by_category") or {}).items():
        label = CATEGORY_LABELS.get(cat, cat)
        lines.append(f"| {label} | {data['passed']} / {data['total']} | {data['rate']:.0%} |")
    lines.append("")

    failures = summary.get("failures") or {}
    lines.append("## 失败归因")
    lines.append("")
    if not failures:
        lines.append("本轮没有失败样本。")
    else:
        lines.append("| 类别 | 数量 | 说明 |")
        lines.append("|---|---|---|")
        for key, count in sorted(failures.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{key}` | {count} | {FAILURE_LABELS.get(key, key)} |")
    lines.append("")

    lines.append("## 逐题结果")
    lines.append("")
    lines.append("| 题号 | 类别 | 结果 | 覆盖率 | 落地率 | 成本 | 归因 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        mark = "✅" if r.passed else "❌"
        failure = FAILURE_LABELS.get(r.failure, r.failure or "")
        lines.append(
            f"| {r.id} | {CATEGORY_LABELS.get(r.category, r.category)} | {mark} | "
            f"{r.coverage:.0%} | {r.grounded_rate:.0%} | ¥{r.cost_cny} | {failure} |"
        )
    lines.append("")

    lines.append("## 口径说明")
    lines.append("")
    lines.append("- 分母是全部题，失败题同样计入成功率")
    lines.append("- 通过标准：覆盖 ≥ 2/3 要点且无事实错误；无解题以「是否明确拒答」判定")
    lines.append("- 覆盖率与落地率均由程序计算，judge 只负责要点判定，需定期人工校准")
    return "\n".join(lines)


def write_summary(out_dir: Path, summary: dict[str, Any], results: list[QuestionResult], meta: dict[str, Any]) -> Path:
    path = out_dir / "summary.md"
    path.write_text(render_markdown(summary, results, meta), encoding="utf-8")
    write_csv(out_dir / "summary.csv", results)
    return path
