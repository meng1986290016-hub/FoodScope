"""Feishu/Lark Card JSON 2.0 rendering for FoodScope briefs."""

from __future__ import annotations

import json
from typing import Any, Iterable

from src.models import ContentItem

from .briefing import (
    BriefFacts,
    RenderedBrief,
    partition_brief_items,
)
from .rendering import (
    published_beijing,
    source_label,
    source_url,
)


FEISHU_BODY_LIMIT = 25_000
_CONTENT_CHUNK = 18_000


def _markdown(content: str) -> dict[str, str]:
    return {"tag": "markdown", "content": content}


def _plain(content: str) -> dict[str, str]:
    return {"tag": "plain_text", "content": content}


def _source_url(item: ContentItem) -> str:
    return source_url(item)


def _title(item: ContentItem) -> str:
    return str(
        item.metadata.get("title_zh") or item.title
    ).replace("[", "［").replace("]", "］")


def _linked_title(item: ContentItem) -> str:
    url = _source_url(item)
    title = _title(item)
    return f"[{title}]({url})" if url else title


def _item_detail(item: ContentItem) -> str:
    if item.food is None:
        return f"**{_linked_title(item)}**"
    food = item.food
    lines = [
        f"**{_linked_title(item)}**",
        f"- 发生了什么：{food.what_happened_zh}",
    ]
    if food.key_facts_zh:
        lines.append(
            "- 关键事实：\n"
            + "\n".join(
                f"  - {fact}" for fact in food.key_facts_zh
            )
        )
    lines.extend(
        [
            (
                "- 市场 / 分类："
                f"{', '.join(food.markets)} / "
                f"{food.category.value}"
            ),
            f"- 原始来源：[{source_label(item)}]({_source_url(item)})",
            f"- 发布日期：{published_beijing(item.published_at)}",
        ]
    )
    return "\n".join(line for line in lines if line)


def _item_list(
    heading: str, items: Iterable[ContentItem]
) -> dict[str, str] | None:
    rows = [
        f"{index}. {_linked_title(item)}"
        for index, item in enumerate(items, start=1)
    ]
    if not rows:
        return None
    return _markdown(
        f"## {heading}\n" + "\n".join(rows)
    )


def _panel(
    title: str, content: str
) -> dict[str, Any]:
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": _plain(title),
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
            },
            "icon_position": "right",
        },
        "border": {
            "color": "grey",
            "corner_radius": "5px",
        },
        "elements": [_markdown(content)],
    }


def _footer(facts_hash: str) -> dict[str, str]:
    return _markdown(
        "---\n"
        "AI 辅助整理，请回到原始证据复核。"
        f"\n事实快照 SHA-256：`{facts_hash}`"
    )


def _card(
    title: str,
    elements: list[dict[str, Any]],
    facts_hash: str,
    *,
    template: str = "green",
) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
                "update_multi": True,
            },
            "header": {
                "title": _plain(title),
                "template": template,
            },
            "body": {
                "elements": elements + [_footer(facts_hash)]
            },
        },
    }


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _chunks(content: str) -> list[str]:
    if len(content) <= _CONTENT_CHUNK:
        return [content]
    chunks: list[str] = []
    remaining = content
    while remaining:
        candidate = remaining[:_CONTENT_CHUNK]
        split_at = candidate.rfind("\n")
        if split_at > _CONTENT_CHUNK // 2:
            candidate = candidate[:split_at]
        chunks.append(candidate)
        remaining = remaining[len(candidate) :].lstrip("\n")
    return chunks


def _split_element(
    element: dict[str, Any]
) -> list[dict[str, Any]]:
    if element.get("tag") == "markdown":
        return [
            _markdown(chunk)
            for chunk in _chunks(str(element["content"]))
        ]
    if element.get("tag") == "collapsible_panel":
        content = str(
            element.get("elements", [{}])[0].get(
                "content", ""
            )
        )
        title = str(
            element.get("header", {})
            .get("title", {})
            .get("content", "详情")
        )
        chunks = _chunks(content)
        return [
            _panel(
                title if index == 0 else f"{title}（续）",
                chunk,
            )
            for index, chunk in enumerate(chunks)
        ]
    return [element]


def _pack_cards(
    *,
    title: str,
    elements: list[dict[str, Any]],
    facts_hash: str,
    template: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    expanded = [
        split
        for element in elements
        for split in _split_element(element)
    ]
    for element in expanded:
        candidate = _card(
            title,
            current + [element],
            facts_hash,
            template=template,
        )
        if (
            current
            and _serialized_size(candidate)
            >= FEISHU_BODY_LIMIT
        ):
            cards.append(
                _card(
                    title,
                    current,
                    facts_hash,
                    template=template,
                )
            )
            current = [element]
        else:
            current.append(element)
        single = _card(
            title,
            current,
            facts_hash,
            template=template,
        )
        if _serialized_size(single) >= FEISHU_BODY_LIMIT:
            raise ValueError(
                "one Feishu card element exceeds the body limit"
            )
    if current or not cards:
        cards.append(
            _card(
                title,
                current,
                facts_hash,
                template=template,
            )
        )
    return cards


def build_feishu_brief_payload(
    facts: BriefFacts, rendered: RenderedBrief
) -> list[dict[str, Any]]:
    """Render canonical facts as size-bounded Card JSON 2.0 payloads."""
    if facts.fact_hash() != rendered.facts_sha256:
        raise ValueError(
            "rendered brief does not match canonical facts"
        )
    metadata = facts.metadata
    overview = _markdown(
        "# 食界雷达 · 全球食品产业简报\n"
        f"> {metadata.date} · {metadata.profile_name} "
        f"（{metadata.profile_id}）\n\n"
        f"抓取 {metadata.fetched_count} 条 · "
        f"候选 {metadata.candidate_count} 条 · "
        f"入选 {metadata.selected_count} 条 · "
        f"隔离 {metadata.isolated_count} 条"
    )
    overview_elements: list[dict[str, Any]] = [overview]
    section_items = [
        item
        for items in facts.sections.values()
        for item in items
    ]
    must_read_items, news_items = partition_brief_items(
        facts.must_read + facts.news + section_items,
        facts.risk_alerts,
    )
    must_read_list = _item_list(
        "今日必读", must_read_items
    )
    news_list = _item_list("今日新闻", news_items)
    if must_read_list is not None:
        overview_elements.append(must_read_list)
    if news_list is not None:
        overview_elements.append(news_list)
    if facts.observations:
        overview_elements.append(
            _markdown(
                "## 观察与待验证信号\n"
                + "\n".join(
                    f"- {observation}"
                    for observation in facts.observations
                )
            )
        )

    payloads = _pack_cards(
        title=f"FoodScope {metadata.date} 总览",
        elements=overview_elements,
        facts_hash=rendered.facts_sha256,
        template="green",
    )
    for label, items in (
        ("今日必读", must_read_items),
        ("今日新闻", news_items),
    ):
        if not items:
            continue
        section_content = "\n\n---\n\n".join(
            _item_detail(item) for item in items
        )
        payloads.extend(
            _pack_cards(
                title=(
                    f"FoodScope {metadata.date} · {label}"
                ),
                elements=[_panel(label, section_content)],
                facts_hash=rendered.facts_sha256,
                template="green",
            )
        )
    return payloads
