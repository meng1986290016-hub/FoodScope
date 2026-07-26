"""Configurable metadata-first HTML listing adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem
from src.url_security import safe_request

from .base import BaseFoodAdapter


class HTMLListAdapter(BaseFoodAdapter):
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
        item_selector = self._required_option(
            source, "item_selector"
        )
        self._detail_date_fetches = 0
        items: list[ContentItem] = []
        for index, element in enumerate(soup.select(item_selector)):
            self.raw_candidate_count += 1
            parsed = await self._parse_element(
                source, element, since, until, index
            )
            if parsed is not None:
                items.append(parsed)
        return items

    async def _parse_element(
        self,
        source: FoodSourceSpec,
        element: Tag,
        since: datetime,
        until: datetime | None,
        index: int,
    ) -> ContentItem | None:
        title_node = element.select_one(
            self._required_option(source, "title_selector")
        )
        link_node = element.select_one(
            self._required_option(source, "link_selector")
        )
        date_node = element.select_one(
            self._required_option(source, "date_selector")
        )
        if title_node is None or link_node is None:
            return None
        href = link_node.get(
            source.options.get("link_attribute", "href")
        )
        if not href:
            return None
        url = self.absolute_url(str(source.url), href)
        published = self._node_date(date_node, source)
        if published is None:
            published = await self._detail_page_date(source, url)
        self.note_date_result(published)
        if published is None:
            if not source.options.get("allow_undated", False):
                return None
            published = datetime.now(timezone.utc)
        if not self.in_window(published, since, until):
            return None
        content_node = (
            element.select_one(source.options["content_selector"])
            if source.options.get("content_selector")
            else None
        )
        return self.make_item(
            source,
            title=title_node.get_text(" ", strip=True),
            url=url,
            published_at=published,
            content=self.bounded_text(
                (
                    content_node.get_text(" ", strip=True)
                    if content_node is not None
                    else None
                ),
                source,
            ),
            native_id=self.native_id(url, str(index)),
            metadata={
                "list_url": str(source.url),
                "language": (
                    source.languages[0]
                    if source.languages
                    else None
                ),
            },
        )

    def _node_date(
        self, node: Tag | None, source: FoodSourceSpec
    ) -> datetime | None:
        if node is None:
            return None
        attribute = source.options.get(
            "date_attribute", "datetime"
        )
        raw = node.get(attribute) or node.get_text(" ", strip=True)
        return self.parse_date(raw)

    async def _detail_page_date(
        self, source: FoodSourceSpec, url: str
    ) -> datetime | None:
        selector = source.options.get("detail_date_selector")
        if not isinstance(selector, str) or not selector:
            return None
        max_fetches = int(
            source.options.get("max_detail_date_fetches", 0)
        )
        if max_fetches <= 0 or self._detail_date_fetches >= max_fetches:
            return None
        self._detail_date_fetches += 1
        response = await safe_request(self.client, "GET", url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.select_one(selector)
        if node is None:
            return None
        attribute = source.options.get(
            "detail_date_attribute",
            source.options.get("date_attribute", "datetime"),
        )
        raw = node.get(attribute) or node.get_text(" ", strip=True)
        return self.parse_date(raw)

    @staticmethod
    def _required_option(
        source: FoodSourceSpec, name: str
    ) -> str:
        value = source.options.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"html_list requires option {name}")
        return value
