"""pytest 公共夹具。

本机沙箱下 tempfile.mkdtemp 创建的目录会丢权限，pytest 的 tmp_path 正好基于它。
所以这里改用工作区内的固定目录，由普通 mkdir 创建。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

WORK_DIR = Path(__file__).resolve().parents[1] / ".work" / "pytest-tmp"


@pytest.fixture
def db_path() -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    path = WORK_DIR / f"test-{uuid.uuid4().hex[:10]}.db"
    yield path
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            pass
