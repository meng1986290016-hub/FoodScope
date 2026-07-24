"""FoodScope wrapper around Horizon's Google News behavior."""

from __future__ import annotations

from datetime import datetime

from src.foodscope.config import FoodSourceSpec
from src.models import (
    ContentItem,
    GoogleNewsConfig,
)
from src.scrapers.google_news import GoogleNewsScraper

from .base import BaseFoodAdapter


class GoogleNewsFoodAdapter(BaseFoodAdapter):
    async def fetch(
        self, source: FoodSourceSpec, since: datetime
    ) -> list[ContentItem]:
        options = source.options
        language = source.languages[0] if source.languages else "en"
        market = next(
            (
                value
                for value in source.markets
                if len(value) == 2
            ),
            "US",
        )
        category_hint = options.get("category_hint", [])
        category = (
            category_hint[0]
            if isinstance(category_hint, list) and category_hint
            else str(category_hint or "")
        )
        scraper = GoogleNewsScraper(
            GoogleNewsConfig(
                enabled=True,
                query=str(options["query"]),
                language=language,
                country=market,
                max_results=int(
                    options.get(
                        "max_candidates_per_provider", 20
                    )
                ),
                category=category,
            ),
            self.client,
        )
        raw_items = await scraper.fetch(since)
        return [
            self._convert(source, item) for item in raw_items
        ]

    def _convert(
        self, source: FoodSourceSpec, item: ContentItem
    ) -> ContentItem:
        metadata = self.metadata(
            source,
            discovery_provider="google_news",
            discovery_query=source.options["query"],
            discovered_source_name=item.metadata.get("source_name"),
            language=(
                source.languages[0]
                if source.languages
                else None
            ),
        )
        return self.make_item(
            source,
            title=item.title,
            url=str(item.url),
            published_at=item.published_at,
            content=self.bounded_text(item.content, source),
            author=item.author,
            native_id=(
                "google_news-"
                + self.native_id(str(item.url), item.id)
            ),
            metadata=metadata,
        )
