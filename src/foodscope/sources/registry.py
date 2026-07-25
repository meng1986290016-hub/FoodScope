"""Manifest adapter registry with per-source failure isolation."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from hashlib import sha256
import random
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import CollectionTier
from src.error_utils import safe_error_detail
from src.models import ContentItem
from src.orchestrator import SourceFetchOutcome

from .base import BaseFoodAdapter
from .discovery_query import DiscoveryQueryAdapter
from .documents import DocumentIndexAdapter
from .html_list import HTMLListAdapter
from .json_api import JSONAPIAdapter
from .rss import RSSFoodAdapter
from .x_official_api import XOfficialAPIAdapter


ADAPTERS: dict[str, type[BaseFoodAdapter]] = {
    "rss": RSSFoodAdapter,
    "json_api": JSONAPIAdapter,
    "html_list": HTMLListAdapter,
    "document_index": DocumentIndexAdapter,
    "discovery_query": DiscoveryQueryAdapter,
    "x_official_api": XOfficialAPIAdapter,
}


def _fallback_sort_key(
    source: FoodSourceSpec, business_date: date
) -> tuple[int, str, str]:
    return (
        0
        if source.collection_tier == CollectionTier.EXTENDED
        else 1,
        sha256(
            (
                f"{business_date.isoformat()}:"
                f"{source.id}"
            ).encode("utf-8")
        ).hexdigest(),
        source.id,
    )


def order_fallback_sources(
    sources: list[FoodSourceSpec],
    *,
    business_date: date,
) -> list[FoodSourceSpec]:
    """Return enabled fallback candidates in a stable daily order."""
    return sorted(
        (source for source in sources if source.enabled),
        key=lambda source: _fallback_sort_key(
            source, business_date
        ),
    )


def select_sources_for_run(
    sources: list[FoodSourceSpec],
    *,
    business_date: date,
    minimum_sources: int,
    extended_rotation_days: int,
    discovery_rotation_days: int,
) -> list[FoodSourceSpec]:
    """Choose a stable tier-aware subset for one business day."""
    enabled = [source for source in sources if source.enabled]
    selected: list[FoodSourceSpec] = []
    deferred: list[FoodSourceSpec] = []
    ordinal = business_date.toordinal()
    intervals = {
        CollectionTier.EXTENDED: extended_rotation_days,
        CollectionTier.DISCOVERY: discovery_rotation_days,
    }

    for source in enabled:
        if source.collection_tier == CollectionTier.CORE:
            selected.append(source)
            continue
        interval = intervals[source.collection_tier]
        bucket = int(
            sha256(source.id.encode("utf-8")).hexdigest(), 16
        ) % interval
        if bucket == ordinal % interval:
            selected.append(source)
        else:
            deferred.append(source)

    if len(selected) < minimum_sources:
        deferred = order_fallback_sources(
            deferred, business_date=business_date
        )
        selected.extend(
            deferred[: max(0, minimum_sources - len(selected))]
        )

    selected_ids = {source.id for source in selected}
    return [
        source for source in enabled if source.id in selected_ids
    ]


class FoodSourceRegistry:
    _ATTEMPTS = {
        CollectionTier.CORE: 3,
        CollectionTier.EXTENDED: 2,
        CollectionTier.DISCOVERY: 1,
    }
    _PRIORITY = {
        CollectionTier.CORE: 0,
        CollectionTier.EXTENDED: 1,
        CollectionTier.DISCOVERY: 2,
    }

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        max_concurrency: int = 8,
        per_domain_concurrency: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if per_domain_concurrency < 1:
            raise ValueError(
                "per_domain_concurrency must be positive"
            )
        self.client = http_client
        self.max_concurrency = max_concurrency
        self.per_domain_concurrency = per_domain_concurrency
        self.sleep = sleep
        self.jitter = jitter

    async def fetch(
        self,
        sources: list[FoodSourceSpec],
        since: datetime,
        until: datetime | None = None,
    ) -> tuple[list[ContentItem], list[SourceFetchOutcome]]:
        global_semaphore = asyncio.Semaphore(
            self.max_concurrency
        )
        domain_semaphores: dict[str, asyncio.Semaphore] = {}

        async def one(
            original_index: int, source: FoodSourceSpec
        ) -> tuple[int, SourceFetchOutcome]:
            domain = urlsplit(source.url).hostname or source.id
            domain_semaphore = domain_semaphores.setdefault(
                domain,
                asyncio.Semaphore(self.per_domain_concurrency),
            )
            adapter_type = ADAPTERS.get(source.adapter)
            if adapter_type is None:
                return (
                    original_index,
                    SourceFetchOutcome(
                        source.id,
                        "failure",
                        error="FoodScope source fetch failed (KeyError)",
                    ),
                )
            adapter = adapter_type(self.client)
            last_error: Exception | None = None
            attempts = self._ATTEMPTS[source.collection_tier]
            for attempt in range(1, attempts + 1):
                adapter.reset_metrics()
                try:
                    async with domain_semaphore:
                        async with global_semaphore:
                            items = await adapter.fetch(
                                source, since, until
                            )
                    return (
                        original_index,
                        SourceFetchOutcome(
                            source.id,
                            "success" if items else "empty",
                            items=items,
                            candidate_count=len(items),
                            published_at_candidate_count=(
                                adapter.date_parse_attempts
                            ),
                            published_at_parse_count=(
                                adapter.date_parse_successes
                            ),
                        ),
                    )
                except Exception as error:
                    last_error = error
                if attempt < attempts:
                    await self.sleep(
                        self._retry_delay(last_error, attempt)
                    )
            return (
                original_index,
                SourceFetchOutcome(
                    source.id,
                    "failure",
                    error=safe_error_detail(
                        last_error,
                        "FoodScope source fetch failed",
                    ),
                    candidate_count=0,
                    published_at_candidate_count=(
                        adapter.date_parse_attempts
                    ),
                    published_at_parse_count=(
                        adapter.date_parse_successes
                    ),
                ),
            )

        indexed_sources = [
            (index, source)
            for index, source in enumerate(sources)
            if source.enabled
        ]
        indexed_sources.sort(
            key=lambda value: (
                self._PRIORITY[value[1].collection_tier],
                value[0],
            )
        )
        indexed_outcomes = list(
            await asyncio.gather(
                *(
                    one(index, source)
                    for index, source in indexed_sources
                )
            )
        )
        indexed_outcomes.sort(key=lambda value: value[0])
        outcomes = [outcome for _, outcome in indexed_outcomes]
        return (
            [
                item
                for outcome in outcomes
                for item in outcome.items
            ],
            outcomes,
        )

    def _retry_delay(
        self,
        error: Exception | None,
        attempt: int,
    ) -> float:
        response = getattr(error, "response", None)
        if response is not None:
            raw_retry_after = response.headers.get("Retry-After")
            try:
                if raw_retry_after is not None:
                    return min(
                        60.0, max(0.0, float(raw_retry_after))
                    )
            except (TypeError, ValueError):
                pass
        exponential = min(30.0, 0.5 * (2 ** (attempt - 1)))
        return exponential + 0.25 * self.jitter()
