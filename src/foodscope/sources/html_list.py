"""Configurable metadata-first HTML listing adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
import httpx

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
        self._detail_content_fetches = 0
        self._detail_page_cache: dict[str, BeautifulSoup | None] = {}
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
        exclude_pattern = source.options.get("exclude_text_pattern")
        if (
            isinstance(exclude_pattern, str)
            and exclude_pattern
            and re.search(
                exclude_pattern,
                element.get_text(" ", strip=True),
            )
        ):
            return None
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
        include_pattern = source.options.get("url_include_pattern")
        if (
            isinstance(include_pattern, str)
            and include_pattern
            and re.search(include_pattern, url) is None
        ):
            return None
        published = self._node_date(date_node, source)
        if (
            published is None
            or source.options.get("prefer_detail_date", False)
        ):
            detail_published = await self._detail_page_date(
                source, url
            )
            if detail_published is not None:
                published = detail_published
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
        content = self.bounded_text(
            (
                content_node.get_text(" ", strip=True)
                if content_node is not None
                else None
            ),
            source,
        )
        if source.options.get("detail_content_selector"):
            detail_content = await self._detail_page_content(
                source, url
            )
            if detail_content is not None:
                content = detail_content
        if source.options.get("require_content", False) and not content:
            return None
        return self.make_item(
            source,
            title=title_node.get_text(" ", strip=True),
            url=url,
            published_at=published,
            content=content,
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
        pattern = source.options.get("date_text_pattern")
        if isinstance(pattern, str) and pattern:
            match = re.search(pattern, str(raw))
            if match is None:
                return None
            raw = match.group(1) if match.lastindex else match.group(0)
        return self.parse_date(raw)

    async def _detail_page_date(
        self, source: FoodSourceSpec, url: str
    ) -> datetime | None:
        selector = source.options.get("detail_date_selector")
        jsonld_field = source.options.get(
            "detail_date_jsonld_field"
        )
        has_selector = isinstance(selector, str) and bool(selector)
        has_jsonld_field = (
            isinstance(jsonld_field, str) and bool(jsonld_field)
        )
        if not has_selector and not has_jsonld_field:
            return None
        max_fetches = int(
            source.options.get("max_detail_date_fetches", 0)
        )
        if max_fetches <= 0 or self._detail_date_fetches >= max_fetches:
            return None
        self._detail_date_fetches += 1
        soup = await self._detail_page_soup(url)
        if soup is None:
            return None
        if has_selector:
            node = soup.select_one(str(selector))
            if node is not None:
                attribute = source.options.get(
                    "detail_date_attribute",
                    source.options.get(
                        "date_attribute", "datetime"
                    ),
                )
                raw = node.get(attribute) or node.get_text(
                    " ", strip=True
                )
                parsed = self.parse_date(raw)
                if parsed is not None:
                    return parsed
        if has_jsonld_field:
            return self._jsonld_date(soup, str(jsonld_field))
        return None

    @classmethod
    def _jsonld_date(
        cls, soup: BeautifulSoup, field: str
    ) -> datetime | None:
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for value in cls._nested_field_values(payload, field):
                parsed = cls.parse_date(value)
                if parsed is not None:
                    return parsed
        return None

    @classmethod
    def _nested_field_values(
        cls, value: Any, field: str
    ) -> list[Any]:
        if isinstance(value, dict):
            found = [value[field]] if field in value else []
            for nested in value.values():
                found.extend(
                    cls._nested_field_values(nested, field)
                )
            return found
        if isinstance(value, list):
            found = []
            for nested in value:
                found.extend(
                    cls._nested_field_values(nested, field)
                )
            return found
        return []

    async def _detail_page_content(
        self, source: FoodSourceSpec, url: str
    ) -> str | None:
        selector = source.options.get("detail_content_selector")
        if not isinstance(selector, str) or not selector:
            return None
        max_fetches = int(
            source.options.get("max_detail_content_fetches", 0)
        )
        if (
            max_fetches <= 0
            or self._detail_content_fetches >= max_fetches
        ):
            return None
        self._detail_content_fetches += 1
        soup = await self._detail_page_soup(url)
        if soup is None:
            return None
        node = soup.select_one(selector)
        if node is None:
            return None
        return self.bounded_text(
            node.get_text(" ", strip=True), source
        )

    async def _detail_page_soup(
        self, url: str
    ) -> BeautifulSoup | None:
        if url in self._detail_page_cache:
            return self._detail_page_cache[url]
        try:
            response = await safe_request(self.client, "GET", url)
            response.raise_for_status()
        except httpx.HTTPError:
            self._detail_page_cache[url] = None
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        self._detail_page_cache[url] = soup
        return soup

    @staticmethod
    def _required_option(
        source: FoodSourceSpec, name: str
    ) -> str:
        value = source.options.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"html_list requires option {name}")
        return value
