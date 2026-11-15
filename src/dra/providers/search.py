"""搜索 Provider：Tavily 为主，博查为备（简单降级链）。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import Settings
from ..trace import Tracer


class SearchError(RuntimeError):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0


class TavilySearch:
    name = "tavily"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._http = httpx.Client(timeout=settings.search_timeout)

    def close(self) -> None:
        self._http.close()

    def search(self, query: str) -> list[SearchResult]:
        if not self.s.search_api_key:
            raise SearchError("SEARCH_API_KEY 未配置")
        resp = self._http.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.s.search_api_key,
                "query": query,
                "max_results": self.s.search_max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        if resp.status_code != 200:
            raise SearchError(f"Tavily HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        out = []
        for item in data.get("results") or []:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            out.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    content=(item.get("content") or "").strip(),
                    score=float(item.get("score") or 0.0),
                )
            )
        return out


class BochaSearch:
    name = "bocha"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._http = httpx.Client(timeout=settings.search_timeout)

    def close(self) -> None:
        self._http.close()

    def search(self, query: str) -> list[SearchResult]:
        if not self.s.bocha_api_key:
            raise SearchError("BOCHA_API_KEY 未配置")
        resp = self._http.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {self.s.bocha_api_key}"},
            json={"query": query, "count": self.s.search_max_results, "summary": True, "freshness": "noLimit"},
        )
        if resp.status_code != 200:
            raise SearchError(f"Bocha HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
        out = []
        for item in pages:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            summary = item.get("summary") or item.get("snippet") or ""
            out.append(
                SearchResult(
                    title=(item.get("name") or "").strip(),
                    url=url,
                    content=summary.strip(),
                    score=0.0,
                )
            )
        return out


class SearchChain:
    """按顺序尝试多个 provider，任一成功即返回。"""

    def __init__(self, providers: list) -> None:
        self.providers = providers

    @property
    def name(self) -> str:
        return "+".join(p.name for p in self.providers) or "none"

    def close(self) -> None:
        for p in self.providers:
            try:
                p.close()
            except Exception:
                pass

    def search(self, query: str, tracer: Tracer) -> list[SearchResult]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                with tracer.span("search", kind="tool", provider=provider.name, query=query) as span:
                    results = provider.search(query)
                    span.set(results=len(results))
                if results:
                    return results
                errors.append(f"{provider.name}: 0 条结果")
            except Exception as exc:  # 降级到下一个 provider
                errors.append(f"{provider.name}: {exc}")
        raise SearchError("；".join(errors) or "无可用搜索源")


def build_search(settings: Settings) -> SearchChain:
    if settings.search_provider == "bocha":
        primary = BochaSearch(settings)
        secondary = TavilySearch(settings) if settings.search_api_key else None
    else:
        primary = TavilySearch(settings)
        secondary = BochaSearch(settings) if settings.bocha_api_key else None
    providers = [p for p in (primary, secondary) if p is not None]
    return SearchChain(providers)
