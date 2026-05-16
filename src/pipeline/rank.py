from __future__ import annotations

import logging
import math

from ..fetchers.base import Item

log = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "llm_score": 1.0,
    "mention_count": 0.6,
    "hn_points": 0.5,
    "reddit_score": 0.4,
    "altmetric": 0.3,
    "citations": 0.3,
}


def _log_scale(x: float | int | None) -> float:
    if not x or x <= 0:
        return 0.0
    return math.log10(x + 1)


def compute_final_score(item: Item, w: dict[str, float] = DEFAULT_WEIGHTS) -> float:
    extra = item.extra
    llm = float(extra.get("score", 3))
    mentions = int(extra.get("mention_count", 1))
    hn_points = extra.get("points") if "hn" in item.source_id else None
    reddit_score = extra.get("score") if "reddit" in item.source_id else None
    altmetric = extra.get("altmetric_score")
    citations = extra.get("citation_count")

    final = (
        w["llm_score"] * (llm / 5.0) * 5.0
        + w["mention_count"] * _log_scale(mentions - 1) * 3.0
        + w["hn_points"] * _log_scale(hn_points)
        + w["reddit_score"] * _log_scale(reddit_score)
        + w["altmetric"] * _log_scale(altmetric)
        + w["citations"] * _log_scale(citations)
    )
    item.extra["final_score"] = round(final, 2)
    return final


def rank_and_cap(
    items: list[Item],
    per_category_cap: int = 25,
) -> list[Item]:
    for it in items:
        compute_final_score(it)

    by_cat: dict[str, list[Item]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)

    capped: list[Item] = []
    for cat, lst in by_cat.items():
        lst.sort(key=lambda x: x.extra.get("final_score", 0), reverse=True)
        keep = lst[:per_category_cap]
        log.info("rank %s: %d → top %d (final_score range %.2f → %.2f)",
                 cat, len(lst), len(keep),
                 keep[0].extra.get("final_score", 0) if keep else 0,
                 keep[-1].extra.get("final_score", 0) if keep else 0)
        capped.extend(keep)

    capped.sort(key=lambda x: x.extra.get("final_score", 0), reverse=True)
    return capped
