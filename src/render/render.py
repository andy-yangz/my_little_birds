from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..fetchers.base import Item

TEMPLATE_DIR = Path(__file__).parent / "templates"

CATEGORY_LABELS = {"ai": "AI", "econ": "经济", "macro": "宏观", "micro": "微观"}


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["cat_label"] = lambda c: CATEGORY_LABELS.get(c, c)
    return env


def _score_to_stars(score: float) -> int:
    if score >= 6: return 5
    if score >= 4.5: return 4
    if score >= 3: return 3
    if score >= 1.5: return 2
    return 1


def _enrich_clusters(items: list[Item], clusters: list[dict]) -> list[dict]:
    by_url = {it.url: it for it in items}
    out = []
    for c in clusters:
        members = [by_url[s["url"]] for s in c.get("sources", []) if s["url"] in by_url]
        if not members:
            members = []
        scores = [m.extra.get("final_score", 0) for m in members] or [0]
        c["stars"] = _score_to_stars(max(scores))
        c["max_mention_count"] = max((m.extra.get("mention_count", 1) for m in members), default=1)
        c["max_hn_points"] = max((m.extra.get("points") or 0 for m in members), default=0) or None
        c["max_altmetric"] = max((m.extra.get("altmetric_score") or 0 for m in members), default=0) or None
        c["max_citations"] = max((m.extra.get("citation_count") or 0 for m in members), default=0) or None
        out.append(c)
    out.sort(key=lambda x: x.get("stars", 0), reverse=True)
    return out


def render_daily(
    items: list[Item],
    date: datetime,
    out_dir: Path,
    *,
    summaries: dict | None = None,
    filename: str | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    tpl = env.get_template("daily.html.j2")

    by_category: dict[str, list[Item]] = {}
    for it in items:
        by_category.setdefault(it.category, []).append(it)
    for cat in by_category:
        by_category[cat].sort(key=lambda x: x.extra.get("final_score", 0), reverse=True)

    enriched_summaries: dict[str, list[dict]] = {}
    if summaries:
        for cat, clusters in summaries.items():
            cat_items = by_category.get(cat, [])
            enriched_summaries[cat] = _enrich_clusters(cat_items, clusters)

    html = tpl.render(
        date=date,
        date_str=date.strftime("%Y-%m-%d"),
        by_category=by_category,
        total=len(items),
        summaries=enriched_summaries,
    )

    fname = filename or f"{date.strftime('%Y-%m-%d')}.html"
    out_path = out_dir / fname
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_index(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    tpl = env.get_template("index.html.j2")
    dailies = sorted(
        [p.name for p in out_dir.glob("20*.html") if p.name != "index.html"],
        reverse=True,
    )
    html = tpl.render(dailies=dailies)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
