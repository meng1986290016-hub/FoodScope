"""Evidence-bounded second-pass enrichment for selected FoodScope items."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from src.ai.client import AIClient
from src.ai.utils import parse_json_response
from src.models import ContentItem

from .prompts import FOOD_ENRICHMENT_SYSTEM, FOOD_ENRICHMENT_USER


class FoodEnrichmentResult(BaseModel):
    what_happened_zh: str
    why_it_matters_zh: str
    rd_significance_zh: str = ""
    opportunity_signal_zh: str
    risk_signal_zh: str = ""
    recommended_action_zh: str


class FoodContentEnricher:
    """Deeply enrich selected items while isolating per-item failures."""

    def __init__(
        self,
        ai_client: AIClient,
        *,
        max_attempts: int = 3,
        concurrency: int = 4,
        timeout_seconds: float = 60.0,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = ai_client
        self.max_attempts = max_attempts
        self.concurrency = concurrency
        self.timeout_seconds = timeout_seconds

    async def enrich(
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def enrich_one(item: ContentItem) -> ContentItem:
            async with semaphore:
                return await self._enrich_with_isolation(item)

        return list(
            await asyncio.gather(
                *(enrich_one(item) for item in items)
            )
        )

    async def _enrich_with_isolation(
        self, item: ContentItem
    ) -> ContentItem:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            item.metadata["foodscope_enrichment_attempts"] = attempt
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    result = await self._enrich_once(item)
                self._apply_result(item, result)
                return item
            except Exception as error:
                last_error = error

        item.metadata["foodscope_isolated"] = True
        item.metadata["foodscope_isolation_stage"] = "enriched"
        item.metadata["foodscope_analysis_error"] = (
            str(last_error) if last_error else "unknown enrichment error"
        )
        return item

    async def _enrich_once(
        self, item: ContentItem
    ) -> FoodEnrichmentResult:
        food = item.food
        if food is None:
            raise ValueError(
                "FoodScope enrichment requires food intelligence"
            )
        response = await self.client.complete(
            system=FOOD_ENRICHMENT_SYSTEM,
            user=FOOD_ENRICHMENT_USER.format(
                title=item.metadata.get("title_zh", item.title),
                summary_zh=item.ai_summary or "",
                category=food.category.value,
                markets=", ".join(food.markets),
                risk_level=food.risk_level.value,
                risk_reason=food.risk_reason,
                original_url=food.original_source_url or str(item.url),
                evidence_urls=", ".join(food.evidence_urls),
                content=(item.content or "")[:6000],
            ),
        )
        parsed = parse_json_response(response)
        if parsed is None:
            raise ValueError("enrichment response was not valid JSON")
        return FoodEnrichmentResult.model_validate(parsed)

    @staticmethod
    def _apply_result(
        item: ContentItem, result: FoodEnrichmentResult
    ) -> None:
        food = item.food
        if food is None:
            raise ValueError(
                "FoodScope enrichment requires food intelligence"
            )
        food.what_happened_zh = result.what_happened_zh
        food.why_it_matters_zh = result.why_it_matters_zh
        food.rd_significance_zh = result.rd_significance_zh
        food.opportunity_signal_zh = result.opportunity_signal_zh
        food.risk_signal_zh = result.risk_signal_zh
        food.recommended_action_zh = result.recommended_action_zh
