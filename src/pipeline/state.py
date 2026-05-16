from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..fetchers.base import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_id TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen(first_seen);
"""


class State:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def filter_unseen(self, items: list[Item], lookback_days: int = 30) -> list[Item]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        self.conn.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
        cur = self.conn.execute("SELECT url FROM seen WHERE first_seen >= ?", (cutoff,))
        seen = {row[0] for row in cur.fetchall()}
        return [it for it in items if it.url not in seen]

    def mark_seen(self, items: list[Item]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen(url, title, source_id, first_seen) VALUES (?, ?, ?, ?)",
            [(it.url, it.title, it.source_id, now) for it in items],
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
