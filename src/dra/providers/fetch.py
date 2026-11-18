"""网页抓取与正文抽取。"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ..config import Settings
from ..recording import Recorder, make_key
from ..trace import Tracer
from ..util import truncate

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_BLOCK_RE = re.compile(r"</?(p|div|br|li|h[1-6]|tr|section|article)[^>]*>", re.I)


@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int = 0
    title: str = ""
    text: str = ""
    error: str | None = None


class Fetcher:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.recorder = Recorder(settings.run_mode, settings.fixtures_dir)
        self._http = httpx.Client(
            timeout=settings.fetch_timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )

    def close(self) -> None:
        self._http.close()

    def fetch(self, url: str, tracer: Tracer | None = None) -> Page:
        key = make_key("fetch", url)
        if self.recorder.mode == "mock":
            payload = self.recorder.require("fetch", key, hint=f"url={url}")
            return Page(
                url=payload.get("url", url),
                final_url=payload.get("final_url", url),
                status=int(payload.get("status", 200)),
                title=payload.get("title", ""),
                text=payload.get("text", ""),
                error=payload.get("error"),
            )

        page = self._fetch_live(url)
        if self.recorder.mode == "record":
            # 失败的页面也要录：否则重放时这一页会凭空消失，导致证据数与录制时不一致
            self.recorder.save(
                "fetch",
                key,
                {
                    "url": page.url,
                    "final_url": page.final_url,
                    "status": page.status,
                    "title": page.title,
                    "text": page.text,
                    "error": page.error,
                },
            )
        return page

    def _fetch_live(self, url: str) -> Page:
        page = Page(url=url)
        try:
            resp = self._http.get(url)
        except Exception as exc:
            page.error = f"{type(exc).__name__}: {exc}"
            return page

        page.status = resp.status_code
        page.final_url = str(resp.url)
        if resp.status_code != 200:
            page.error = f"HTTP {resp.status_code}"
            return page

        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            page.error = f"不支持的内容类型: {content_type[:60]}"
            return page

        raw = resp.content[: self.s.fetch_max_bytes]
        html = raw.decode(resp.encoding or "utf-8", "ignore")
        page.title = _extract_title(html)
        page.text = extract_text(html)
        if not page.text:
            page.error = "正文抽取为空"
        return page


def extract_text(html: str) -> str:
    """优先 trafilatura，失败回退到标签剥离。"""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            no_fallback=False,
        )
        if text and len(text.strip()) > 80:
            return _normalize(text)
    except Exception:
        pass
    return _normalize(_strip_tags(html))


def _strip_tags(html: str) -> str:
    html = _TAG_RE.sub(" ", html)
    html = _BLOCK_RE.sub("\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        html = html.replace(entity, char)
    return html


def _normalize(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return _normalize(m.group(1)) if m else ""


def make_snippet(text: str, limit: int = 300) -> str:
    return truncate(text.replace("\n", " "), limit)
