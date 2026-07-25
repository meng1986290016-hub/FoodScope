"""FoodScope wrapper around Horizon's GDELT behavior."""

from __future__ import annotations

from datetime import datetime

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem, GDELTConfig
from src.scrapers.gdelt import GDELTScraper

from .base import BaseFoodAdapter


_GDELT_LANGUAGES = {
    "en": "english",
    "ja": "japanese",
    "ko": "korean",
}


class GDELTFoodAdapter(BaseFoodAdapter):
    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        options = source.options
        language = source.languages[0] if source.languages else "en"
        category_hint = options.get("category_hint", [])
        category = (
            category_hint[0]
            if isinstance(category_hint, list) and category_hint
            else str(category_hint or "")
        )
        scraper = GDELTScraper(
            GDELTConfig(
                enabled=True,
                query=str(options["query"]),
                max_records=int(
                    options.get(
                        "max_candidates_per_provider", 20
                    )
                ),
                language=_GDELT_LANGUAGES.get(language),
                category=category,
            ),
            self.client,
        )
        raw_items = await scraper.fetch(since, until)
        self.raw_candidate_count = scraper.raw_candidate_count
        self.date_parse_attempts = scraper.date_parse_attempts
        self.date_parse_successes = scraper.date_parse_successes
        return [
            self._convert(source, item) for item in raw_items
        ]

    def _convert(
        self, source: FoodSourceSpec, item: ContentItem
    ) -> ContentItem:
        return self.make_item(
            source,
            title=item.title,
            url=str(item.url),
            published_at=item.published_at,
            content=self.bounded_text(item.content, source),
            author=item.author,
            native_id=(
                "gdelt-" + self.native_id(str(item.url), item.id)
            ),
            metadata={
                "discovery_provider": "gdelt",
                "discovery_query": source.options["query"],
                "resolved_original_url": str(item.url),
                "discovered_domain": item.metadata.get("domain"),
                "language": (
                    source.languages[0]
                    if source.languages
                    else None
                ),
            },
        )
