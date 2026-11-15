"""链路追踪：span 树同时写入 SQLite 与 JSONL，用于事后归因。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .store import Store
from .util import now_iso, short_id


class Span:
    def __init__(self, tracer: "Tracer", name: str, kind: str, parent_id: str | None, attrs: dict[str, Any]):
        self.tracer = tracer
        self.id = short_id(12)
        self.name = name
        self.kind = kind
        self.parent_id = parent_id
        self.attrs = attrs
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_cny = 0.0
        self.status = "ok"
        self.error: str | None = None
        self._t0 = 0.0

    def set(self, **kwargs: Any) -> "Span":
        self.attrs.update(kwargs)
        return self

    def usage(self, tokens_in: int, tokens_out: int, cost_cny: float) -> "Span":
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_cny = cost_cny
        return self

    def __enter__(self) -> "Span":
        self._t0 = time.perf_counter()
        self.tracer._push(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        dur_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc is not None:
            self.status = "error"
            self.error = f"{exc_type.__name__}: {exc}" if exc_type else str(exc)
        self.tracer._pop(self)
        record = {
            "id": self.id,
            "run_id": self.tracer.run_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "ts_start": self.attrs.pop("_ts_start", None),
            "ts_end": now_iso(),
            "dur_ms": dur_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_cny": round(self.cost_cny, 6),
            "status": self.status,
            "attrs": self.attrs,
            "error": self.error,
        }
        self.tracer._write(record)


class Tracer:
    def __init__(self, run_id: str, trace_dir: Path, store: Store) -> None:
        self.run_id = run_id
        self.store = store
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.path = trace_dir / f"{run_id}.jsonl"
        self._stack: list[Span] = []

    def span(self, name: str, kind: str = "internal", **attrs: Any) -> Span:
        parent = self._stack[-1].id if self._stack else None
        attrs["_ts_start"] = now_iso()
        return Span(self, name, kind, parent, attrs)

    def _push(self, span: Span) -> None:
        self._stack.append(span)

    def _pop(self, span: Span) -> None:
        if self._stack and self._stack[-1] is span:
            self._stack.pop()
        else:
            self._stack = [s for s in self._stack if s is not span]

    def _write(self, record: dict[str, Any]) -> None:
        self.store.add_span(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
