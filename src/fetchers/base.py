from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Item:
    source_id: str
    source_name: str
    category: str
    title: str
    url: str
    published: Optional[datetime]
    summary: str = ""
    author: str = ""
    extra: dict = field(default_factory=dict)


class FetchError(Exception):
    pass
