"""零散工具函数。"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse


def setup_console() -> None:
    """统一控制台为 UTF-8。

    不再按 GetConsoleOutputCP 猜测编码：Terminal/conhost 的代码页与实际渲染
    可能不一致，统一强制 UTF-8 才不会出现"一半乱码"。
    """
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def short_id(n: int = 8) -> str:
    return hashlib.sha1(str(datetime.now().timestamp()).encode()).hexdigest()[:n]
