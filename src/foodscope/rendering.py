"""Render one BriefFacts snapshot to authoritative Markdown and HTML."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, select_autoescape

from src.ai.summarizer import _escape_markdown, _safe_url
from src.models import ContentItem

from .briefing import (
    BriefFacts,
    RenderedBrief,
    partition_brief_items,
)
from .models import FoodCategory


CATEGORY_LABELS = {
    FoodCategory.PRODUCT_INNOVATION.value: "产品创新与新品",
    FoodCategory.INGREDIENTS_TECHNOLOGY.value: "原料与技术",
    FoodCategory.PACKAGING_LABELING.value: "包装与标签",
    FoodCategory.CONSUMER_TRENDS.value: "消费趋势",
    FoodCategory.REGULATIONS_STANDARDS.value: "法规与标准",
    FoodCategory.FOOD_SAFETY_RECALLS.value: "食品安全与召回",
    FoodCategory.RETAIL_FOODSERVICE.value: "零售与餐饮",
    FoodCategory.COMPANY_UPDATES.value: "企业动态",
}


def _category_label(value: object) -> str:
    return CATEGORY_LABELS.get(str(value), str(value))


def _item_tags(item: ContentItem) -> list[str]:
    if item.food is None:
        return list(item.ai_tags)
    return list(
        dict.fromkeys(
            item.food.product_tags
            + item.food.ingredient_tags
            + item.food.technology_tags
            + item.food.company_tags
        )
    )


def source_url(item: ContentItem) -> str:
    candidate = (
        item.food.original_source_url
        if item.food is not None
        and item.food.original_source_url
        else str(item.url)
    )
    return _safe_url(candidate) or ""


def source_label(item: ContentItem) -> str:
    for key in ("discovered_source_name", "source_name"):
        value = item.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if item.author and item.author.strip():
        return item.author.strip()
    hostname = urlsplit(source_url(item)).hostname or "原文"
    return hostname.removeprefix("www.")


def published_beijing(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
        "%Y-%m-%d %H:%M（北京时间）"
    )


class FoodBriefRenderer:
    def __init__(self) -> None:
        loader = PackageLoader("src.foodscope", "templates")
        self.markdown_environment = Environment(
            loader=loader,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.html_environment = Environment(
            loader=loader,
            autoescape=select_autoescape(
                enabled_extensions=("html.j2", "html")
            ),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        for environment in (
            self.markdown_environment,
            self.html_environment,
        ):
            environment.filters.update(
                {
                    "md": _escape_markdown,
                    "safe_url": lambda value: _safe_url(value) or "",
                    "category_label": _category_label,
                    "item_tags": _item_tags,
                    "source_url": source_url,
                    "source_label": source_label,
                    "published_beijing": published_beijing,
                }
            )

    def render(self, facts: BriefFacts) -> RenderedBrief:
        facts_hash = facts.fact_hash()
        section_items = [
            item
            for items in facts.sections.values()
            for item in items
        ]
        must_read, news = partition_brief_items(
            facts.must_read + facts.news + section_items,
            facts.risk_alerts,
        )
        context = {
            "facts": facts,
            "facts_hash": facts_hash,
            "must_read": must_read,
            "news": news,
        }
        markdown = self.markdown_environment.get_template(
            "brief.md.j2"
        ).render(**context)
        html = self.html_environment.get_template(
            "brief.html.j2"
        ).render(**context)
        return RenderedBrief(
            facts_sha256=facts_hash,
            markdown=markdown.rstrip() + "\n",
            html=html.rstrip() + "\n",
        )
