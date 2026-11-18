"""评测 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import REPO_ROOT, Settings
from ..util import setup_console
from .dataset import DatasetError, load_dataset
from .runner import EvalOptions, rejudge, run_eval


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dra.eval", description="跑评测集并输出指标")
    p.add_argument("--dataset", default=str(REPO_ROOT / "eval" / "dataset" / "v1.jsonl"), help="数据集路径")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 题（冒烟用）")
    p.add_argument("--tag", default="", help="给这批结果打标签，便于对比")
    p.add_argument("--max-cny", type=float, default=0.0, help="总成本上限，超出即停")
    p.add_argument("--resume", action="store_true", help="跳过已有结果的题")
    p.add_argument("--no-cache", action="store_true", help="禁用搜索缓存（时效题评测用）")
    p.add_argument("--out", default=str(REPO_ROOT / ".work" / "eval"), help="结果输出目录")
    p.add_argument("--quiet", action="store_true", help="不打印逐题进度")
    p.add_argument("--dry-run", action="store_true", help="只校验数据集，不实际运行")
    p.add_argument("--rejudge", default="", help="对已有结果目录只重跑判分（不重跑 agent）")
    return p


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    settings = Settings.load()
    if args.no_cache:
        from dataclasses import replace

        settings = replace(settings, search_cache=False)

    try:
        questions = load_dataset(Path(args.dataset))
    except DatasetError as exc:
        print(f"❌ 数据集错误：{exc}")
        return 2

    if args.dry_run:
        categories: dict[str, int] = {}
        for q in questions:
            categories[q.category] = categories.get(q.category, 0) + 1
        print(f"数据集 OK：{len(questions)} 题")
        for cat, count in sorted(categories.items()):
            print(f"  {cat:<12} {count}")
        return 0

    if args.rejudge:
        try:
            rejudge(settings, Path(args.dataset), Path(args.rejudge), quiet=args.quiet)
        except (FileNotFoundError, ValueError) as exc:
            print(f"❌ {exc}")
            return 2
        return 0

    options = EvalOptions(
        dataset=Path(args.dataset),
        out_dir=Path(args.out),
        limit=args.limit,
        tag=args.tag,
        max_cny=args.max_cny,
        resume=args.resume,
        quiet=args.quiet,
    )
    summary_path = run_eval(settings, options)
    print(f"摘要：{summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
