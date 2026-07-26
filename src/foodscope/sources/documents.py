"""Metadata-only document-index adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem
from src.url_security import safe_request

from .html_list import HTMLListAdapter


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".hwpx": (
        "application/vnd.hancom.hwpx"
    ),
    ".docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
}


class DocumentIndexAdapter(HTMLListAdapter):
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
        soup = BeautifulSoup(response.text, "html.parser")
        selector = self._required_option(source, "item_selector")
        self._detail_date_fetches = 0
        items: list[ContentItem] = []
        for index, element in enumerate(soup.select(selector)):
            self.raw_candidate_count += 1
            item = await self._parse_element(
                source, element, since, until, index
            )
            if item is None:
                continue
            item.content = None
            suffix = PurePosixPath(
                urlsplit(str(item.url)).path
            ).suffix.lower()
            item.metadata.update(
                {
                    "document_index": True,
                    "media_type": source.options.get(
                        "media_type",
                        _MEDIA_TYPES.get(
                            suffix, "application/octet-stream"
                        ),
                    ),
                    "full_document_collected": False,
                }
            )
            items.append(item)
        return items
