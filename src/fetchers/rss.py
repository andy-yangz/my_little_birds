from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import httpx
from dateutil import parser as dateparser

from .base import Item, FetchError

log = logging.getLogger(__name__)

USER_AGENT = "my_little_birds/0.1 (+https://github.com/y1z11/my_little_birds)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


async def _get(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (tuple, list)) and len(value) >= 6:
        return datetime(*value[:6], tzinfo=timezone.utc)
    try:
        dt = dateparser.parse(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def fetch_rss(source: dict) -> list[Item]:
    sid = source["id"]
    url = source["url"]
    async with httpx.AsyncClient(timeout=TIMEOUT, http2=True) as client:
        try:
            raw = await _get(client, url)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            raise FetchError(f"{sid}: HTTP fail — {e}") from e

    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        raise FetchError(f"{sid}: parse fail — {feed.bozo_exception}")

    items: list[Item] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _parse_dt(
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("published")
            or entry.get("updated")
        )
        summary = entry.get("summary") or entry.get("description") or ""
        author = entry.get("author") or ""
        items.append(
            Item(
                source_id=sid,
                source_name=source["name"],
                category=source.get("category", "misc"),
                title=title,
                url=link,
                published=published,
                summary=summary,
                author=author,
            )
        )
    log.info("rss %s — %d items", sid, len(items))
    return items


async def fetch_many_rss(sources: Iterable[dict]) -> list[Item]:
    tasks = [fetch_rss(s) for s in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[Item] = []
    for s, r in zip(sources, results):
        if isinstance(r, Exception):
            log.warning("source %s failed: %s", s["id"], r)
            continue
        out.extend(r)
    return out
