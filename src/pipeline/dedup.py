from __future__ import annotations

import logging

from rapidfuzz import fuzz

from ..fetchers.base import Item
from .normalize import normalize_url, normalize_title

log = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 88


def dedup(items: list[Item]) -> list[Item]:
    by_url: dict[str, list[Item]] = {}
    for it in items:
        norm = normalize_url(it.url)
        it.url = norm
        by_url.setdefault(norm, []).append(it)

    deduped: list[Item] = []
    for norm, group in by_url.items():
        primary = max(group, key=lambda x: (x.published or _epoch(), len(x.summary or "")))
        for alt in group:
            if alt is primary:
                continue
            primary.extra.setdefault("alts", []).append(
                {"url": alt.url, "source": alt.source_name}
            )
        deduped.append(primary)

    kept: list[Item] = []
    seen_titles: list[tuple[str, Item]] = []
    for it in sorted(deduped, key=lambda x: x.published or _epoch(), reverse=True):
        nt = normalize_title(it.title).lower()
        merged = False
        for prev_title, prev_item in seen_titles:
            if fuzz.token_set_ratio(nt, prev_title) >= TITLE_SIMILARITY_THRESHOLD:
                prev_item.extra.setdefault("alts", []).append(
                    {"url": it.url, "source": it.source_name}
                )
                merged = True
                break
        if not merged:
            seen_titles.append((nt, it))
            kept.append(it)

    for it in kept:
        sources = {it.source_name}
        for a in it.extra.get("alts", []):
            sources.add(a["source"])
        it.extra["mention_count"] = len(sources)
        it.extra["mention_sources"] = sorted(sources)

    log.info("dedup: %d → %d items (mention_count attached)", len(items), len(kept))
    return kept


def _epoch():
    from datetime import datetime, timezone
    return datetime(1970, 1, 1, tzinfo=timezone.utc)
