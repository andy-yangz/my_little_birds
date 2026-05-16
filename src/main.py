from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .fetchers import fetch_rss, fetch_hn, fetch_reddit, Item, FetchError
from .pipeline.dedup import dedup
from .pipeline.enrich import enrich
from .pipeline.rank import rank_and_cap
from .pipeline.score import score_items
from .pipeline.state import State
from .pipeline.summarize import summarize_by_category
from .render.render import render_daily, render_index

log = logging.getLogger("my_little_birds")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.yaml"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

FETCHERS = {"rss": fetch_rss, "hackernews": fetch_hn, "reddit": fetch_reddit}


async def fetch_one(source: dict) -> list[Item]:
    fn = FETCHERS.get(source["type"])
    if fn is None:
        log.warning("unknown source type %s for %s", source["type"], source["id"])
        return []
    try:
        return await fn(source)
    except FetchError as e:
        log.warning("fetch failed: %s", e)
        return []
    except Exception as e:
        log.exception("unexpected error fetching %s: %s", source["id"], e)
        return []


async def run(args: argparse.Namespace) -> int:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    if args.source:
        sources = [s for s in sources if s["id"] == args.source]
        if not sources:
            log.error("no enabled source matches %s", args.source)
            return 1

    log.info("fetching %d sources", len(sources))
    results = await asyncio.gather(*(fetch_one(s) for s in sources))
    all_items: list[Item] = [it for batch in results for it in batch]
    log.info("collected %d raw items", len(all_items))

    if args.since_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
        before = len(all_items)
        all_items = [it for it in all_items if it.published is None or it.published >= cutoff]
        log.info("date filter (last %dh): %d → %d items", args.since_hours, before, len(all_items))

    deduped = dedup(all_items)

    state = State(DATA_DIR / "state.db")
    try:
        if args.no_state:
            fresh = deduped
        else:
            fresh = state.filter_unseen(deduped, lookback_days=30)
            log.info("after state filter: %d new items", len(fresh))

        if args.no_ai:
            scored = fresh
            ranked = fresh[:args.per_category_cap * 2]
            summaries = {}
        else:
            scored = score_items(fresh, min_score=args.min_score)
            if not args.no_enrich:
                await enrich(scored)
            ranked = rank_and_cap(scored, per_category_cap=args.per_category_cap)
            summaries = summarize_by_category(ranked)

        date = datetime.now(timezone.utc) if not args.date else datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
        out = render_daily(
            ranked,
            date,
            DOCS_DIR,
            summaries=summaries,
            filename=("test.html" if args.dry_run else None),
        )
        log.info("rendered %s", out)

        if not args.dry_run:
            state.mark_seen(fresh)
            render_index(DOCS_DIR)
    finally:
        state.close()

    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write to docs/test.html, do not update state or index")
    ap.add_argument("--no-state", action="store_true", help="skip state filtering (include already-seen items)")
    ap.add_argument("--source", help="run a single source by id")
    ap.add_argument("--date", help="override date (ISO YYYY-MM-DD)")
    ap.add_argument("--since-hours", type=int, default=48, help="only keep items published in last N hours (0 = disable)")
    ap.add_argument("--no-ai", action="store_true", help="skip LLM scoring and summarization")
    ap.add_argument("--no-enrich", action="store_true", help="skip Altmetric / Semantic Scholar lookups")
    ap.add_argument("--min-score", type=int, default=3, help="drop items scored below this (1-5)")
    ap.add_argument("--per-category-cap", type=int, default=25, help="max items kept per category after ranking")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
