from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from .base import Item, FetchError

log = logging.getLogger(__name__)


async def fetch_reddit(source: dict) -> list[Item]:
    sid = source["id"]
    try:
        import praw
    except ImportError as e:
        raise FetchError(f"{sid}: praw not installed") from e

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise FetchError(f"{sid}: missing REDDIT_CLIENT_ID/SECRET env vars")

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="my_little_birds/0.1",
    )
    reddit.read_only = True

    sub = reddit.subreddit(source["subreddit"])
    listing = source.get("listing", "top")
    time_filter = source.get("time_filter", "day")
    limit = int(source.get("limit", 25))

    posts = getattr(sub, listing)(time_filter=time_filter, limit=limit) if listing == "top" \
        else getattr(sub, listing)(limit=limit)

    items: list[Item] = []
    for p in posts:
        if p.stickied:
            continue
        items.append(
            Item(
                source_id=sid,
                source_name=source["name"],
                category=source.get("category", "ai"),
                title=p.title,
                url=p.url if not p.is_self else f"https://reddit.com{p.permalink}",
                published=datetime.fromtimestamp(p.created_utc, tz=timezone.utc),
                summary=(p.selftext[:500] if p.is_self else f"r/{source['subreddit']}: {p.score} upvotes, {p.num_comments} comments"),
                author=str(p.author) if p.author else "[deleted]",
                extra={"score": p.score, "permalink": f"https://reddit.com{p.permalink}"},
            )
        )
    log.info("reddit %s — %d items", sid, len(items))
    return items
