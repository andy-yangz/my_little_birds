from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from .base import Item, FetchError

log = logging.getLogger(__name__)

ALGOLIA_API = "https://hn.algolia.com/api/v1/search"


async def fetch_hn(source: dict) -> list[Item]:
    sid = source["id"]
    query = source.get("query", "")
    min_points = int(source.get("min_points", 50))
    hours = int(source.get("hours_back", 36))
    numeric = [f"created_at_i>{int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())}",
               f"points>={min_points}"]
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": ",".join(numeric),
        "hitsPerPage": 50,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(ALGOLIA_API, params=params)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise FetchError(f"{sid}: HN API fail — {e}") from e

    items: list[Item] = []
    for hit in data.get("hits", []):
        title = hit.get("title") or hit.get("story_title") or ""
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        if not title:
            continue
        published = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
        items.append(
            Item(
                source_id=sid,
                source_name=source["name"],
                category=source.get("category", "ai"),
                title=title,
                url=url,
                published=published,
                summary=f"HN: {hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments",
                author=hit.get("author", ""),
                extra={"points": hit.get("points"), "hn_id": hit["objectID"]},
            )
        )
    log.info("hn %s — %d items", sid, len(items))
    return items
