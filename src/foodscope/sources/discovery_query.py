"""Dispatch one multilingual discovery query across allowed providers."""

from __future__ import annotations

import asyncio
from datetime import datetime

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem

from .base import BaseFoodAdapter
from .gdelt import GDELTFoodAdapter
from .google_news import GoogleNewsFoodAdapter


PROVIDERS: dict[str, type[BaseFoodAdapter]] = {
    "google_news": GoogleNewsFoodAdapter,
    "gdelt": GDELTFoodAdapter,
}


class DiscoveryQueryAdapter(BaseFoodAdapter):
    async def fetch(
        self, source: FoodSourceSpec, since: datetime
    ) -> list[ContentItem]:
        provider_names = source.options.get("providers", [])
        if not isinstance(provider_names, list) or not provider_names:
            raise ValueError(
                "discovery_query requires non-empty providers"
            )
        results = await asyncio.gather(
            *(
                PROVIDERS[name](self.client).fetch(source, since)
                for name in provider_names
            ),
            return_exceptions=True,
        )
        provider_errors = [
            result
            for result in results
            if isinstance(result, Exception)
        ]
        collected = [
            item
            for result in results
            if isinstance(result, list)
            for item in result
        ]
        if provider_errors and not collected:
            raise RuntimeError(
                "all discovery providers failed: "
                + "; ".join(str(error) for error in provider_errors)
            )

        deduplicated: list[ContentItem] = []
        seen: set[tuple[str, str]] = set()
        for item in collected:
            key = (str(item.url), item.title.casefold())
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(item)
        limit = int(
            source.options.get("max_candidates_after_dedup", 12)
        )
        return deduplicated[: max(0, limit)]
