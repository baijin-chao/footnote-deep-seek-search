"""内部数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pending", "running", "done", "failed", "skipped"]


@dataclass
class SubQuestion:
    id: int
    run_id: str
    text: str
    order_no: int
    status: Status = "pending"


@dataclass
class Evidence:
    id: int
    run_id: str
    sub_q_id: int
    url: str
    title: str
    domain: str
    snippet: str
    content: str
    content_hash: str
    credibility: float = 0.5


@dataclass
class Stats:
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    searches: int = 0
    fetches: int = 0

    def add_llm(self, tokens_in: int, tokens_out: int, cost_cny: float) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_cny += cost_cny


@dataclass
class RunRecord:
    id: str
    question: str
    status: str = "running"
    mode: str = "live"
    stats: Stats = field(default_factory=Stats)
