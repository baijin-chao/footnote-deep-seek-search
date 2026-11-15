"""Reader：抓取搜索结果正文，去重并打分。"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..providers.fetch import Fetcher, make_snippet
from ..providers.search import SearchResult
from ..trace import Tracer
from ..util import domain_of, sha1, truncate

# 常见权威域名，用于粗粒度可信度打分
_TRUSTED_SUFFIX = (".gov", ".edu", ".gov.cn", ".edu.cn", ".org")
_TRUSTED_HOSTS = (
    "arxiv.org",
    "nature.com",
    "science.org",
    "ieee.org",
    "acm.org",
    "who.int",
    "worldbank.org",
    "oecd.org",
    "stats.gov.cn",
    "cnnic.net.cn",
    "caict.ac.cn",
)


@dataclass
class Document:
    url: str
    title: str
    text: str
    snippet: str
    domain: str
    content_hash: str
    credibility: float


def score_credibility(domain: str) -> float:
    if not domain:
        return 0.4
    if any(host in domain for host in _TRUSTED_HOSTS):
        return 0.9
    if domain.endswith(_TRUSTED_SUFFIX):
        return 0.8
    if domain.endswith((".com", ".cn", ".net", ".io", ".co")):
        return 0.6
    return 0.5


class Reader:
    def __init__(self, settings: Settings, fetcher: Fetcher) -> None:
        self.s = settings
        self.fetcher = fetcher

    def read(
        self,
        results: list[SearchResult],
        tracer: Tracer,
        *,
        per_question: int = 3,
        seen_hashes: set[str] | None = None,
    ) -> list[Document]:
        seen = seen_hashes if seen_hashes is not None else set()
        docs: list[Document] = []
        for result in results[:per_question]:
            with tracer.span("fetch", kind="tool", url=result.url) as span:
                page = self.fetcher.fetch(result.url)
                if page.error or not page.text:
                    span.set(error=page.error or "空正文")
                    continue
                text = truncate(page.text, 12_000)
                digest = sha1(text)
                if digest in seen:
                    span.set(deduped=True)
                    continue
                seen.add(digest)
                domain = domain_of(page.final_url or result.url)
                doc = Document(
                    url=page.final_url or result.url,
                    title=page.title or result.title,
                    text=text,
                    snippet=make_snippet(page.text),
                    domain=domain,
                    content_hash=digest,
                    credibility=score_credibility(domain),
                )
                span.set(title=doc.title, chars=len(text), credibility=doc.credibility)
                docs.append(doc)
        return docs
