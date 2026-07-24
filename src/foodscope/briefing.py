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
    must_read: list[ContentItem] = Field(
        default_factory=list, max_length=5
    )
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


class RenderedBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    facts_sha256: str
    markdown: str
    html: str
