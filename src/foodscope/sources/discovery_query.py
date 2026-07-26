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
_PROVIDER_CONCURRENCY_LIMITS = {"gdelt": 1}
_PROVIDER_SEMAPHORES: dict[
    tuple[str, int], asyncio.Semaphore
] = {}


def _provider_semaphore(name: str) -> asyncio.Semaphore | None:
    limit = _PROVIDER_CONCURRENCY_LIMITS.get(name)
    if limit is None:
        return None
    loop = asyncio.get_running_loop()
    key = (name, id(loop))
    semaphore = _PROVIDER_SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _PROVIDER_SEMAPHORES[key] = semaphore
    return semaphore


class DiscoveryQueryAdapter(BaseFoodAdapter):
    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        provider_names = source.options.get("providers", [])
        if not isinstance(provider_names, list) or not provider_names:
            raise ValueError(
                "discovery_query requires non-empty providers"
            )
        adapters = [
            (name, PROVIDERS[name](self.client))
            for name in provider_names
        ]
        results = await asyncio.gather(
            *(
                self._fetch_provider(
                    name, adapter, source, since, until
                )
                for name, adapter in adapters
            ),
            return_exceptions=True,
        )
        self.raw_candidate_count = sum(
            adapter.raw_candidate_count for _, adapter in adapters
        )
        self.date_parse_attempts = sum(
            adapter.date_parse_attempts for _, adapter in adapters
        )
        self.date_parse_successes = sum(
            adapter.date_parse_successes
            for _, adapter in adapters
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

    async def _fetch_provider(
        self,
        name: str,
        adapter: BaseFoodAdapter,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None,
    ) -> list[ContentItem]:
        semaphore = _provider_semaphore(name)
        if semaphore is None:
            return await adapter.fetch(source, since, until)
        async with semaphore:
            return await adapter.fetch(source, since, until)
