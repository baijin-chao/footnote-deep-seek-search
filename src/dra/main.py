"""CLI 入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent.machine import ResearchAgent
from .config import REPO_ROOT, Settings
from .util import setup_console


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dra", description="Deep Research Agent")
    p.add_argument("question", nargs="+", help="研究问题")
    p.add_argument("--out", default="", help="报告输出路径（默认 .work/reports/<run_id>.md）")
    p.add_argument("--mode", default="", choices=["", "live", "record", "mock"], help="运行模式")
    p.add_argument("--max-steps", type=int, default=0, help="覆盖预算：最大步数")
    p.add_argument("--max-cny", type=float, default=0.0, help="覆盖预算：最大成本（元）")
    p.add_argument("--quiet", action="store_true", help="只输出最终报告")
    p.add_argument("--no-cache", action="store_true", help="禁用搜索缓存（时效题评测用）")
    return p


def make_printer(quiet: bool):
    def emit(event: str, data: dict) -> None:
        if quiet:
            return
        if event == "run_started":
            print(f"\n▶ 开始研究: {data['question']}")
            print(f"  run_id={data['run_id']}  mode={data['mode']}")
        elif event == "state":
            print(f"\n── [{data['steps']:>2}] {data['state']}")
        elif event == "plan":
            for i, q in enumerate(data["questions"], 1):
                print(f"   {i}. {q}")
        elif event == "search":
            print(f"   ? {data['question']}")
        elif event == "search_done":
            print(f"     ← {data['results']} 条结果")
        elif event == "read_done":
            print(f"     ← 采纳 {data['docs']} 篇正文")
        elif event == "subq_failed":
            print(f"     ! 子问题失败: {data['error'][:120]}")
        elif event == "reflect":
            print(f"   证据 {data['evidence_count']} 条" + (f"，提前结束：{data['stop_reason']}" if data.get("stop_reason") else ""))
        elif event == "verify":
            print(
                f"   引用校验 强支撑 {data['supported']}/{data['total']}，"
                f"弱支撑 {data['weak']}，未证实 {data['unverified']}"
                + (f"，缺编号 {data['missing']}" if data.get("missing") else "")
            )
        elif event == "error":
            print(f"❌ {data['message']}")

    return emit


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)
    settings = Settings.load()
    settings.ensure_dirs()

    if args.max_steps:
        settings = _replace(settings, budget_max_steps=args.max_steps)
    if args.max_cny:
        settings = _replace(settings, budget_max_cny=args.max_cny)
    if args.no_cache:
        settings = _replace(settings, search_cache=False)
    mode = args.mode or settings.run_mode

    question = " ".join(args.question).strip()
    agent = ResearchAgent(settings, emit=make_printer(args.quiet))
    result = agent.run(question, mode=mode)

    report = result.get("report") or ""
    out_path = Path(args.out) if args.out else REPO_ROOT / ".work" / "reports" / f"{result['run_id']}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if report:
        out_path.write_text(report, encoding="utf-8")

    stats = result["stats"]
    print("\n" + "═" * 60)
    print(f"状态: {result['status']}   证据: {stats['evidence']} 条   步数: {stats['steps']}")
    print(f"token: {stats['tokens_in']} in / {stats['tokens_out']} out   成本: ¥{stats['cost_cny']}   耗时: {stats['elapsed_s']}s")
    verify = result.get("verification")
    if verify:
        print(
            f"引用校验: 强支撑 {verify['supported']}/{verify['total']}"
            f"  弱支撑 {verify['weak']}  未证实 {verify['unverified']}"
            f"  落地率 {verify['grounded_rate']:.0%}"
        )
    cache = result.get("cache")
    if cache:
        fuzzy = f"（其中近似 {cache['fuzzy_hits']}）" if cache.get("fuzzy_hits") else ""
        print(
            f"搜索缓存: 命中 {cache['hits']}{fuzzy}  未命中 {cache['misses']}  命中率 {cache['hit_rate']:.0%}"
        )
    if result.get("stop_reason"):
        print(f"提前结束: {result['stop_reason']}")
    if result.get("error"):
        print(f"错误: {result['error']}")
    print(f"trace: {result['trace']}")
    if report:
        print(f"报告: {out_path}")
    print("═" * 60)

    if args.quiet and report:
        print(report)
    return 0 if result["status"] == "done" else 1


def _replace(settings: Settings, **kwargs) -> Settings:
    from dataclasses import replace

    return replace(settings, **kwargs)


if __name__ == "__main__":
    sys.exit(main())
