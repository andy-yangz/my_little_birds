from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from openai import OpenAI

from ..fetchers.base import Item

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
INTERESTS_PATH = ROOT / "config" / "interests.md"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SCORE_MODEL = "deepseek-chat"
BATCH_SIZE = 25


def _system_prompt() -> str:
    interests = INTERESTS_PATH.read_text(encoding="utf-8")
    return f"""你是一个信息过滤助手。根据用户的兴趣描述给每条信息打分，输出严格 JSON。

用户兴趣描述：
{interests}

打分规则：
- 5: 改变用户对某事看法的硬核新信息
- 4: 与用户兴趣高度相关，值得读完
- 3: 相关但可以扫一眼标题就过
- 2: 边缘相关
- 1: 完全不在范围内

输出格式：严格 JSON 对象 {{"scores": [{{"i": <index>, "s": <1-5>, "t": [tags]}}, ...]}}。不要任何解释。"""


def _format_batch(items: list[Item]) -> str:
    lines = []
    for i, it in enumerate(items):
        summary = (it.summary or "")[:300].replace("\n", " ")
        lines.append(f"[{i}] {it.title} | {it.source_name} | {summary}")
    return "\n".join(lines)


def _client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def score_items(items: list[Item], min_score: int = 3) -> list[Item]:
    if not items:
        return []
    if not os.environ.get("DEEPSEEK_API_KEY"):
        log.warning("score: no DEEPSEEK_API_KEY — passing through unscored")
        return items

    client = _client()
    system = _system_prompt()
    kept: list[Item] = []

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        try:
            resp = client.chat.completions.create(
                model=SCORE_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"给以下 {len(batch)} 条信息打分：\n\n{_format_batch(batch)}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2000,
            )
            text = resp.choices[0].message.content or ""
            scores = _parse_scores(text)
            usage = resp.usage
            log.info("score batch %d-%d: prompt=%d completion=%d (cache_hit=%s)",
                     start, start + len(batch) - 1,
                     usage.prompt_tokens, usage.completion_tokens,
                     getattr(usage, "prompt_cache_hit_tokens", None))

            for entry in scores:
                idx = entry.get("i")
                s = entry.get("s")
                if idx is None or s is None or idx >= len(batch):
                    continue
                item = batch[idx]
                item.extra["score"] = int(s)
                item.extra["tags"] = entry.get("t", [])
                if int(s) >= min_score:
                    kept.append(item)
        except Exception as e:
            log.warning("score batch failed: %s — passing batch through", e)
            kept.extend(batch)

    log.info("score: %d → %d items (min_score=%d)", len(items), len(kept), min_score)
    kept.sort(key=lambda x: x.extra.get("score", 0), reverse=True)
    return kept


def _parse_scores(text: str) -> list[dict]:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            return obj.get("scores") or obj.get("results") or []
    except json.JSONDecodeError:
        pass
    log.warning("score parse failed: %r", text[:200])
    return []
