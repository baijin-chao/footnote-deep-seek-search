"""录制回放：把外部响应落到 fixtures/，支持离线重放。

三种模式（`RUN_MODE`）：
- `live`   正常调用外部 API（默认）
- `record` 正常调用，同时把响存进 fixtures/，供之后回放
- `mock`   只读 fixtures/，不发任何网络请求；缺录制时直接报错，不静默降级

用途：演示现场断网、额度耗尽、API 限流时，仍能完整跑一遍。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

MODES = ("live", "record", "mock")


class RecordingError(RuntimeError):
    """mock 模式下缺少录制内容。"""


def make_key(*parts: Any) -> str:
    """把请求参数序列化成稳定哈希，作为文件名。"""
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class Recorder:
    def __init__(self, mode: str, fixtures_dir: Path) -> None:
        self.mode = mode if mode in MODES else "live"
        self.dir = Path(fixtures_dir)

    # ---- 读写 ----
    def load(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self.dir / kind / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def save(self, kind: str, key: str, payload: dict[str, Any]) -> Path:
        path = self.dir / kind / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "kind": kind,
            "key": key,
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "payload": payload,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def require(self, kind: str, key: str, hint: str = "") -> dict[str, Any]:
        """mock 模式下取录制，缺失时给出可操作的报错。"""
        payload = self.load(kind, key)
        if payload is None:
            extra = f"（{hint}）" if hint else ""
            raise RecordingError(
                f"mock 模式下缺少 {kind} 录制{extra}：fixtures/{kind}/{key}.json\n"
                f"请先用 RUN_MODE=record 跑一遍同样的请求来录制。"
            )
        return payload.get("payload", {})
