"""Configurable bounded JSON API adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem
from src.url_security import safe_request

from .base import BaseFoodAdapter


class JSONAPIAdapter(BaseFoodAdapter):
    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        since = self.ensure_utc(since)
        response = await safe_request(
            self.client,
            "GET",
            str(source.url),
            params=source.options.get("params"),
            headers=source.options.get("headers"),
        )
        response.raise_for_status()
        payload = response.json()
        records = self._lookup(
            payload, source.options.get("items_path", "")
        )
        if not isinstance(records, list):
            raise ValueError("configured items_path is not a list")

        title_field = self._required_option(source, "title_field")
        url_field = self._required_option(source, "url_field")
        date_field = self._required_option(source, "date_field")
        content_field = source.options.get("content_field")
        id_field = source.options.get("id_field")
        items: list[ContentItem] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            self.raw_candidate_count += 1
            published = self.parse_date(
                self._lookup(record, date_field)
            )
            self.note_date_result(published)
            if published is None or not self.in_window(
                published, since, until
            ):
                continue
            url = self.absolute_url(
                str(source.url), self._lookup(record, url_field)
            )
            title = str(
                self._lookup(record, title_field) or "Untitled"
            )
            raw_content = (
                self._lookup(record, content_field)
                if content_field
                else None
            )
            native_value = (
                self._lookup(record, id_field)
                if id_field
                else url
            )
            items.append(
                self.make_item(
                    source,
                    title=title,
                    url=url,
                    published_at=published,
                    content=self.bounded_text(raw_content, source),
                    native_id=self.native_id(str(native_value), title),
                    metadata={
                        "api_url": str(source.url),
                        "language": (
                            source.languages[0]
                            if source.languages
                            else None
                        ),
                    },
                )
            )
        return items

    @staticmethod
    def _required_option(
        source: FoodSourceSpec, name: str
    ) -> str:
        value = source.options.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"json_api requires option {name}")
        return value

    @staticmethod
    def _lookup(value: Any, path: str | None) -> Any:
        if not path:
            return value
        current = value
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
