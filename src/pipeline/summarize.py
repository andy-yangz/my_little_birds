from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

from ..fetchers.base import Item

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SUMMARIZE_MODEL = "deepseek-chat"
MAX_ITEMS_PER_CATEGORY = 25
MAX_CLUSTERS_PER_CATEGORY = 8


SYSTEM_AI = """你是一个 AI 领域新闻摘要编辑。给定一批论文/博客/讨论条目，请按事件/话题**激进地聚类**（合并 > 拆分），并为每个聚类生成简洁摘要 + 每条目的目的/结论。

输出严格 JSON 对象：
{"clusters": [{
  "title": "...",
  "summary": "...",
  "indices": [int, ...],
  "tags": ["..."],
  "items": [{"idx": int, "purpose": "...", "conclusion": "..."}]
}]}

每个聚类字段：
- title: 10-20 字的聚类标题，能立刻让读者知道是什么
- summary: 2-3 行聚类整体概述
- indices: 属于这个聚类的条目原始 index 数组
- tags: 2-4 个小写短标签（如 "alignment", "rag", "agent", "moe"）
- items: 覆盖所有 indices，每个 idx 必须有 purpose + conclusion

**每篇文献/条目单独给出"目的"和"结论"**（这是用户最关心的部分）：
- purpose: 1 行，作者/作者团队想做什么、回答什么问题、或解决什么具体问题
  - arXiv 论文："作者问 X 是否能 Y" / "作者提出 X 来解决 Y"
  - 博客/讨论："这篇博客想说明 X" / "讨论焦点是 X 的可行性"
- conclusion: 1-2 行，核心发现/做法/数字。具体优于泛泛
  - 论文：方法 + 数据集 + 关键 metric 提升
  - 博客：核心观点 + 关键论据
  - 避免"取得了显著进展"这种空话

**语言规则（重要）**：
- **聚类 title、summary、purpose、conclusion 都用中文**——扫读快
- 技术术语、模型名、论文常用概念**保留英文原文**：RAG、MoE、fine-tuning、attention、alignment、inference、benchmark、agent、scaling law、CoT、in-context learning、token、prompt、SFT、RLHF...（不要硬翻成"检索增强生成"、"专家混合"等）
- 自然代码切换即可，例："作者提出新的 RAG 评估框架 Deepchecks..."
- 原始 paper/blog title 不归你处理（用户直接看链接），你只负责 cluster 的 title/summary + 每条的 purpose/conclusion

聚类规则：
- **每个分类最多 8 个聚类**，宁少勿多
- 主题相近的条目要大胆合并（例如多篇 RAG 相关论文合成一个 "RAG 进展" 聚类）
- 实在孤立的可以是单 item 聚类，但优先合并
- 只输出 JSON 对象，不要任何前后缀文字"""


SYSTEM_ECON = """你是一个经济学论文摘要编辑。给定一批论文/资讯，请按主题**激进地聚类**，并为每个聚类标注是宏观还是微观。

**subtype 判断**：
- **macro（宏观）**：通胀、利率、汇率、增长、失业率/总就业、货币政策、财政政策、产业政策、人口结构、国际贸易、地缘经济、金融稳定
- **micro（微观）**：家庭/企业/个体行为、特定市场（劳动力、教育、医疗、住房、能源）、博弈论、机制设计、产业组织、应用计量、政策评估（局部）

**每篇文献单独给出"目的"和"结论"**（这是用户最关心的部分）：
- purpose: **中文 1 行**，作者想回答什么具体问题（不要"研究 X"，要"作者问 X 是否会导致 Y"）
- conclusion: **中文 1-2 行**，主要发现 + 关键数字/估计/含义。具体优于泛泛
- 经济学术语可保留英文（GDP、CPI、DID、IV、RDD、p-value...），但句子主体是中文

输出严格 JSON 对象：
{"clusters": [{
  "title": "10-20 字聚类标题",
  "subtype": "macro" 或 "micro",
  "summary": "聚类整体 2-3 行概述",
  "indices": [int, ...],
  "tags": ["..."],
  "items": [{"idx": int, "purpose": "...", "conclusion": "..."}]
}]}

聚类规则：
- 每个 subtype 最多 5 个聚类，宁少勿多
- 主题相近大胆合并
- **cluster title 和 summary 用中文**（扫读快）；原始 paper title 不归你处理
- items 数组覆盖该聚类的所有 indices，每个 idx 必须有 purpose + conclusion
- 只输出 JSON 对象，不要任何前后缀文字"""


SYSTEM = SYSTEM_AI  # backward compat reference; actual dispatch below


def _format_items(items: list[Item]) -> str:
    lines = []
    for i, it in enumerate(items):
        s = it.extra.get("score", "?")
        summary = (it.summary or "")[:250].replace("\n", " ")
        lines.append(f"[{i}] (★{s}) {it.title} | {it.source_name} | {summary}")
    return "\n".join(lines)


def _client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def summarize_by_category(items: list[Item]) -> dict[str, list[dict]]:
    by_cat: dict[str, list[Item]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        log.warning("summarize: no DEEPSEEK_API_KEY — skipping")
        return {}

    client = _client()
    result: dict[str, list[dict]] = {}

    for cat, cat_items in by_cat.items():
        cat_items = cat_items[:MAX_ITEMS_PER_CATEGORY]
        if not cat_items:
            continue
        sys_prompt = SYSTEM_ECON if cat == "econ" else SYSTEM_AI
        max_tok = 12000
        try:
            resp = client.chat.completions.create(
                model=SUMMARIZE_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"分类: {cat}\n\n{_format_items(cat_items)}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=max_tok,
            )
            text = resp.choices[0].message.content or ""
            clusters = _parse_clusters(text)
            for c in clusters:
                indices = c.get("indices", [])
                items_brief = {
                    i["idx"]: i for i in c.get("items", [])
                    if isinstance(i, dict) and isinstance(i.get("idx"), int)
                }
                sources = []
                for idx in indices:
                    if isinstance(idx, int) and 0 <= idx < len(cat_items):
                        it = cat_items[idx]
                        src = {"name": it.source_name, "url": it.url, "title": it.title}
                        brief = items_brief.get(idx, {})
                        if brief.get("purpose"):
                            src["purpose"] = brief["purpose"]
                        if brief.get("conclusion"):
                            src["conclusion"] = brief["conclusion"]
                        sources.append(src)
                c["sources"] = sources
            result[cat] = clusters
            log.info("summarize %s: %d items → %d clusters", cat, len(cat_items), len(clusters))
        except Exception as e:
            log.warning("summarize %s failed: %s", cat, e)

    return result


def _parse_clusters(text: str) -> list[dict]:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            return obj.get("clusters") or obj.get("results") or []
    except json.JSONDecodeError:
        pass
    log.warning("summarize parse failed: %r", text[:300])
    return []
