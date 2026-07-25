"""Render one BriefFacts snapshot to authoritative Markdown and HTML."""

from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

from src.ai.summarizer import _escape_markdown, _safe_url
from src.models import ContentItem

from .briefing import BriefFacts, RenderedBrief
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
                }
            )

    def render(self, facts: BriefFacts) -> RenderedBrief:
        facts_hash = facts.fact_hash()
        featured_ids = {
            item.id
            for item in facts.risk_alerts + facts.must_read
        }
        sections = [
            {
                "id": section_id,
                "label": CATEGORY_LABELS.get(
                    section_id, section_id
                ),
                "items": [
                    item
                    for item in items
                    if item.id not in featured_ids
                ],
            }
            for section_id, items in facts.sections.items()
            if any(
                item.id not in featured_ids for item in items
            )
        ]
        context = {
            "facts": facts,
            "facts_hash": facts_hash,
            "sections": sections,
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
