"""Manifest adapter registry with per-source failure isolation."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem
from src.orchestrator import SourceFetchOutcome

from .base import BaseFoodAdapter
from .documents import DocumentIndexAdapter
from .html_list import HTMLListAdapter
from .json_api import JSONAPIAdapter
from .rss import RSSFoodAdapter


ADAPTERS: dict[str, type[BaseFoodAdapter]] = {
    "rss": RSSFoodAdapter,
    "json_api": JSONAPIAdapter,
    "html_list": HTMLListAdapter,
    "document_index": DocumentIndexAdapter,
}


class FoodSourceRegistry:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client

    async def fetch(
        self,
        sources: list[FoodSourceSpec],
        since: datetime,
    ) -> tuple[list[ContentItem], list[SourceFetchOutcome]]:
        async def one(source: FoodSourceSpec) -> SourceFetchOutcome:
            try:
                adapter_type = ADAPTERS[source.adapter]
                items = await adapter_type(self.client).fetch(
                    source, since
                )
                return SourceFetchOutcome(
                    source.id,
                    "success" if items else "empty",
                    items=items,
                )
            except Exception as exc:
                return SourceFetchOutcome(
                    source.id,
                    "failure",
                    error=f"{type(exc).__name__}: {exc}",
                )

        outcomes = list(
            await asyncio.gather(
                *(
                    one(source)
                    for source in sources
                    if source.enabled
                )
            )
        )
        return (
            [
                item
                for outcome in outcomes
                for item in outcome.items
            ],
            outcomes,
        )
