from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

from ..fetchers.base import Item

log = logging.getLogger(__name__)

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)

OPENALEX = "https://api.openalex.org/works/doi:{}"
CROSSREF = "https://api.crossref.org/works/{}"

CONTACT_EMAIL = os.environ.get("ENRICH_CONTACT_EMAIL", "y1z11@example.com")
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
CONCURRENCY = 4


def _arxiv_id(item: Item) -> str | None:
    m = ARXIV_RE.search(item.url)
    return m.group(1) if m else None


def _doi(item: Item) -> str | None:
    m = DOI_RE.search(item.url + " " + (item.summary or ""))
    if m:
        return m.group(1)
    arxiv = _arxiv_id(item)
    if arxiv:
        return f"10.48550/arXiv.{arxiv}"
    return None


async def _openalex(client: httpx.AsyncClient, item: Item, doi: str) -> bool:
    try:
        r = await client.get(
            OPENALEX.format(doi),
            params={"mailto": CONTACT_EMAIL},
            timeout=TIMEOUT,
        )
        if r.status_code in (404, 429):
            return False
        r.raise_for_status()
        data = r.json()
        cited = data.get("cited_by_count")
        if cited is not None:
            item.extra["citation_count"] = int(cited)
        counts_by_year = data.get("counts_by_year") or []
        if counts_by_year:
            recent = sum(c.get("cited_by_count", 0) for c in counts_by_year[:2])
            item.extra["recent_citations"] = recent
        concepts = data.get("concepts") or []
        if concepts:
            item.extra["openalex_concepts"] = [
                c["display_name"] for c in concepts[:5] if c.get("score", 0) > 0.3
            ]
        return True
    except (httpx.HTTPError, ValueError):
        return False


async def _crossref(client: httpx.AsyncClient, item: Item, doi: str) -> None:
    try:
        r = await client.get(
            CROSSREF.format(doi),
            params={"mailto": CONTACT_EMAIL},
            timeout=TIMEOUT,
        )
        if r.status_code in (404, 429):
            return
        r.raise_for_status()
        msg = r.json().get("message", {})
        cited = msg.get("is-referenced-by-count")
        if cited is not None and "citation_count" not in item.extra:
            item.extra["citation_count"] = int(cited)
    except (httpx.HTTPError, ValueError):
        pass


async def enrich(items: list[Item], top_n: int = 80) -> None:
    candidates = sorted(items, key=lambda x: x.extra.get("score", 0), reverse=True)
    targets = [it for it in candidates[:top_n] if _doi(it)]
    if not targets:
        log.info("enrich: no DOI/arXiv items to enrich")
        return

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _one(client: httpx.AsyncClient, it: Item):
        async with sem:
            doi = _doi(it)
            if not doi:
                return
            ok = await _openalex(client, it, doi)
            if not ok or "citation_count" not in it.extra:
                await _crossref(client, it, doi)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_one(client, it) for it in targets], return_exceptions=True)

    hits_cite = sum(1 for it in targets if "citation_count" in it.extra)
    hits_concept = sum(1 for it in targets if "openalex_concepts" in it.extra)
    log.info(
        "enrich: %d targets → citations=%d, concepts=%d",
        len(targets), hits_cite, hits_concept,
    )
