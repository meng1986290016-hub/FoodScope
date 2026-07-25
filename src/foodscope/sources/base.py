"""Shared adapter contract and bounded item helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
from typing import Any
from urllib.parse import urljoin

import httpx
from dateutil import parser as date_parser
from pydantic import HttpUrl

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem, SourceType


class BaseFoodAdapter(ABC):
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.reset_metrics()

    def reset_metrics(self) -> None:
        self.raw_candidate_count = 0
        self.date_parse_attempts = 0
        self.date_parse_successes = 0

    def note_date_result(
        self, parsed: datetime | None
    ) -> None:
        self.date_parse_attempts += 1
        if parsed is not None:
            self.date_parse_successes += 1

    @abstractmethod
    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        raise NotImplementedError

    @staticmethod
    def ensure_utc(moment: datetime) -> datetime:
        if moment.tzinfo is None:
            return moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)

    @classmethod
    def in_window(
        cls,
        moment: datetime,
        since: datetime,
        until: datetime | None = None,
    ) -> bool:
        observed = cls.ensure_utc(moment)
        return observed >= cls.ensure_utc(since) and (
            until is None or observed <= cls.ensure_utc(until)
        )

    @classmethod
    def parse_date(cls, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return cls.ensure_utc(value)
        try:
            parsed = date_parser.parse(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        return cls.ensure_utc(parsed)

    @staticmethod
    def absolute_url(base: str, candidate: Any) -> str:
        return urljoin(base, str(candidate or "").strip())

    @staticmethod
    def native_id(url: str, fallback: str = "") -> str:
        identity = url or fallback
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def bounded_text(
        value: Any, source: FoodSourceSpec
    ) -> str | None:
        if value is None:
            return None
        limit = int(source.options.get("max_content_chars", 1200))
        normalized = " ".join(str(value).split())
        return normalized[: max(0, min(limit, 4000))] or None

    @staticmethod
    def metadata(
        source: FoodSourceSpec, **extra: Any
    ) -> dict[str, Any]:
        return {
            "food_source_id": source.id,
            "source_name": source.name,
            "source_pack_ids": source.packs,
            "markets": source.markets,
            "languages": source.languages,
            "category_hint": (
                source.categories[0].value
                if source.categories
                else None
            ),
            **extra,
        }

    @classmethod
    def make_item(
        cls,
        source: FoodSourceSpec,
        *,
        title: str,
        url: str,
        published_at: datetime,
        content: str | None = None,
        author: str | None = None,
        native_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContentItem:
        return ContentItem(
            id=(
                f"food:{source.id}:"
                f"{native_id or cls.native_id(url, title)}"
            ),
            source_type=SourceType.FOOD,
            title=title.strip() or "Untitled",
            url=HttpUrl(url),
            content=content,
            author=author or source.name,
            published_at=cls.ensure_utc(published_at),
            metadata=cls.metadata(source, **(metadata or {})),
        )
