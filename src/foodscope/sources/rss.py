"""Bounded RSS/Atom adapter for FoodScope."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

from bs4 import BeautifulSoup
import feedparser

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem
from src.url_security import safe_request

from .base import BaseFoodAdapter


class RSSFoodAdapter(BaseFoodAdapter):
    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        since = self.ensure_utc(since)
        response = await safe_request(
            self.client, "GET", str(source.url)
        )
        response.raise_for_status()
        feed = feedparser.parse(
            re.sub(
                rb"&lt;!\[CDATA\[(.*?)\]\]&gt;",
                rb"<![CDATA[\1]]>",
                response.content,
                flags=re.DOTALL,
            )
        )
        items: list[ContentItem] = []
        for entry in feed.entries:
            self.raw_candidate_count += 1
            published = self._entry_date(entry)
            self.note_date_result(published)
            if published is None or not self.in_window(
                published, since, until
            ):
                continue
            url = self.absolute_url(
                str(source.url),
                entry.get("link") or str(source.url),
            )
            raw_content = (
                entry.get("summary")
                or entry.get("description")
                or (
                    entry.get("content", [{}])[0].get("value")
                    if entry.get("content")
                    else None
                )
            )
            content = None
            if raw_content:
                content = self.bounded_text(
                    self._clean_entry_text(raw_content),
                    source,
                )
            items.append(
                self.make_item(
                    source,
                    title=self._clean_entry_text(
                        entry.get("title", "Untitled")
                    ),
                    url=url,
                    content=content,
                    author=entry.get("author") or source.name,
                    published_at=published,
                    native_id=self.native_id(
                        str(entry.get("id") or url)
                    ),
                    metadata={
                        "feed_url": str(source.url),
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
    def _clean_entry_text(value: object) -> str:
        text = str(value).strip()
        if text.startswith("<![CDATA[") and text.endswith("]]>"):
            text = text[9:-3]
        return BeautifulSoup(text, "html.parser").get_text(
            " ", strip=True
        )

    @classmethod
    def _entry_date(cls, entry) -> datetime | None:
        for field in ("published", "updated", "created"):
            parsed_value = entry.get(f"{field}_parsed")
            if parsed_value:
                return datetime.fromtimestamp(
                    calendar.timegm(parsed_value), tz=timezone.utc
                )
            raw_value = entry.get(field)
            if raw_value:
                try:
                    return cls.ensure_utc(
                        parsedate_to_datetime(raw_value)
                    )
                except (TypeError, ValueError, OverflowError):
                    parsed = cls.parse_date(raw_value)
                    if parsed is not None:
                        return parsed
        return None
