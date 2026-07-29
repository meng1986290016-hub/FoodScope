"""Canonical immutable fact boundary for every FoodScope output."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models import ContentItem

from .models import FoodCategory


class BriefMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    profile_id: str
    profile_name: str
    date: str
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    fetched_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    isolated_count: int = Field(ge=0)
    source_success_count: int = Field(ge=0)
    source_failure_count: int = Field(ge=0)


class BriefFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    metadata: BriefMetadata
    risk_alerts: list[ContentItem] = Field(default_factory=list)
    must_read: list[ContentItem] = Field(default_factory=list)
    news: list[ContentItem] = Field(default_factory=list)
    sections: dict[str, list[ContentItem]] = Field(
        default_factory=dict
    )
    observations: list[str] = Field(default_factory=list)

    @field_validator("sections", mode="before")
    @classmethod
    def order_sections(
        cls, value: Any
    ) -> dict[str, list[Any]]:
        if not isinstance(value, dict):
            raise ValueError("sections must be a mapping")
        category_order = [
            category.value for category in FoodCategory
        ]
        keys = [
            key for key in category_order if key in value
        ] + sorted(key for key in value if key not in category_order)
        ordered: dict[str, list[Any]] = {}
        for key in keys:
            items = list(value[key])

            def selection_order(pair):
                index, item = pair
                if isinstance(item, dict):
                    metadata = item.get("metadata") or {}
                else:
                    metadata = getattr(item, "metadata", {})
                raw = metadata.get("selection_order", index)
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return index

            ordered[key] = [
                item
                for _, item in sorted(
                    enumerate(items), key=selection_order
                )
            ]
        return ordered

    def canonical_json(self) -> str:
        payload = self.model_dump(
            mode="json", exclude_none=True, by_alias=True
        )
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def fact_hash(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()


def _numeric_metadata(
    item: ContentItem, key: str, default: float
) -> float:
    value = item.metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_score(item: ContentItem) -> float:
    if item.food is None:
        return 0.0
    default = (
        0.45 * item.food.importance_score
        + 0.25 * item.food.profile_relevance_score
        + 0.20 * item.food.opportunity_score
        + 0.10 * item.food.evidence_quality_score
    )
    return _numeric_metadata(
        item, "foodscope_base_score", default
    )


def partition_brief_items(
    items: list[ContentItem],
    risk_alerts: list[ContentItem],
    *,
    must_read_score: float = 6.0,
) -> tuple[list[ContentItem], list[ContentItem]]:
    """Return deduplicated score-ordered must-read and news items."""
    unique: dict[str, ContentItem] = {}
    for item in risk_alerts + items:
        unique.setdefault(item.id, item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            -_numeric_metadata(
                item,
                "foodscope_final_score",
                _base_score(item),
            ),
            -item.published_at.timestamp(),
            str(item.url),
        ),
    )
    return (
        [
            item
            for item in ordered
            if _base_score(item) >= must_read_score
        ],
        [
            item
            for item in ordered
            if _base_score(item) < must_read_score
        ],
    )


class RenderedBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    facts_sha256: str
    markdown: str
    html: str
