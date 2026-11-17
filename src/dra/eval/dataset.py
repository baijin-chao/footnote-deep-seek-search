"""评测集加载与校验。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

CATEGORIES = {"fact", "compare", "fresh", "multi_hop", "no_answer"}
DIFFICULTIES = {"easy", "medium", "hard"}
REQUIRED_FIELDS = (
    "id",
    "category",
    "question",
    "must_cover",
    "should_refuse",
    "expected_sources",
    "difficulty",
    "notes",
)


class DatasetError(ValueError):
    """评测集格式错误，报错信息要能直接定位到行。"""


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    must_cover: tuple[str, ...]
    should_refuse: bool
    expected_sources: tuple[str, ...] = ()
    difficulty: str = "medium"
    notes: str = ""

    @property
    def pass_threshold(self) -> int:
        """至少覆盖几条才算通过：2/3 向上取整。

        must_cover 只有 2 条时需要全中，3 条时中 2 条。
        """
        total = len(self.must_cover)
        if total == 0:
            return 0
        return min(total, math.ceil(total * 2 / 3))


def load_dataset(path: Path) -> list[Question]:
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"找不到数据集：{path}")

    questions: list[Question] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"第 {lineno} 行不是合法 JSON：{exc}") from exc

        missing = [f for f in REQUIRED_FIELDS if f not in item]
        if missing:
            raise DatasetError(f"第 {lineno} 行缺少字段：{', '.join(missing)}")

        if item["category"] not in CATEGORIES:
            raise DatasetError(f"第 {lineno} 行 category 非法：{item['category']}")
        if item["difficulty"] not in DIFFICULTIES:
            raise DatasetError(f"第 {lineno} 行 difficulty 非法：{item['difficulty']}")
        if not isinstance(item["must_cover"], list) or not item["must_cover"]:
            raise DatasetError(f"第 {lineno} 行 must_cover 必须是非空数组")
        if item["id"] in seen:
            raise DatasetError(f"第 {lineno} 行 id 重复：{item['id']}")
        if item["category"] == "no_answer" and not item["should_refuse"]:
            raise DatasetError(f"第 {lineno} 行是无解题，但 should_refuse 为 false")

        seen.add(item["id"])
        questions.append(
            Question(
                id=str(item["id"]),
                category=item["category"],
                question=str(item["question"]).strip(),
                must_cover=tuple(str(x) for x in item["must_cover"]),
                should_refuse=bool(item["should_refuse"]),
                expected_sources=tuple(item.get("expected_sources") or ()),
                difficulty=item["difficulty"],
                notes=str(item.get("notes") or ""),
            )
        )

    if not questions:
        raise DatasetError(f"数据集为空：{path}")
    return questions
