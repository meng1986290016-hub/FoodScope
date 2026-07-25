"""Structured, failure-isolated AI analysis for FoodScope content."""

from __future__ import annotations

import asyncio
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.ai.client import AIClient
from src.ai.utils import parse_json_response
from src.error_utils import safe_error_detail
from src.models import ContentItem

from .models import (
    FoodCategory,
    ProductLaunchDetails,
    RiskLevel,
)
from .event_dedup import canonical_url_event_key
from .prompts import FOOD_ANALYSIS_SYSTEM, FOOD_ANALYSIS_USER


class FoodAnalysisResult(BaseModel):
    """Validated model response for one food-industry item."""

    relevant: bool
    title_zh: str = ""
    summary_zh: str = ""
    category: Optional[FoodCategory] = None
    markets: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    ingredient_tags: list[str] = Field(default_factory=list)
    technology_tags: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    importance_score: Optional[float] = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    profile_relevance_score: Optional[float] = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    opportunity_score: Optional[float] = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    evidence_quality_score: Optional[float] = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    risk_level: Optional[RiskLevel] = None
    risk_reason: str = ""
    event_key: Optional[str] = None
    sponsored: bool = False
    press_release: bool = False
    product_launch: Optional[ProductLaunchDetails] = None

    @model_validator(mode="after")
    def require_relevant_fields(self) -> "FoodAnalysisResult":
        if not self.relevant:
            return self
        required = {
            "title_zh": self.title_zh,
            "summary_zh": self.summary_zh,
            "category": self.category,
            "importance_score": self.importance_score,
            "profile_relevance_score": self.profile_relevance_score,
            "opportunity_score": self.opportunity_score,
            "evidence_quality_score": self.evidence_quality_score,
            "risk_level": self.risk_level,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError(
                "relevant analysis missing required fields: "
                + ", ".join(missing)
            )
        return self


class FoodContentAnalyzer:
    """Analyze a batch without allowing one bad model response to stop it."""

    def __init__(
        self,
        ai_client: AIClient,
        *,
        profile_id: str = "balanced",
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
        self.profile_id = profile_id
        self.max_attempts = max_attempts
        self.concurrency = concurrency
        self.timeout_seconds = timeout_seconds

    async def analyze_batch(
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def analyze(item: ContentItem) -> ContentItem:
            async with semaphore:
                return await self._analyze_with_isolation(item)

        return list(await asyncio.gather(*(analyze(item) for item in items)))

    async def _analyze_with_isolation(
        self, item: ContentItem
    ) -> ContentItem:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            item.metadata["foodscope_analysis_attempts"] = attempt
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    result = await self._analyze_once(item)
                self._apply_result(item, result)
                return item
            except Exception as error:
                last_error = error

        item.ai_score = 0.0
        item.ai_reason = "FoodScope analysis failed"
        item.ai_summary = item.title
        item.ai_tags = []
        item.metadata["foodscope_isolated"] = True
        item.metadata["foodscope_analysis_error"] = safe_error_detail(
            last_error, "FoodScope analysis failed"
        )
        return item

    async def _analyze_once(
        self, item: ContentItem
    ) -> FoodAnalysisResult:
        response = await self.client.complete(
            system=FOOD_ANALYSIS_SYSTEM,
            user=FOOD_ANALYSIS_USER.format(
                profile_id=self.profile_id,
                source_name=item.metadata.get("source_name", "Unknown"),
                source_id=item.metadata.get("food_source_id", "unknown"),
                published_at=item.published_at.isoformat(),
                url=str(item.url),
                title=item.title,
                content=(item.content or "")[:6000],
            ),
        )
        parsed = parse_json_response(response)
        if parsed is None:
            raise ValueError("analysis response was not valid JSON")
        return FoodAnalysisResult.model_validate(parsed)

    @staticmethod
    def _apply_result(
        item: ContentItem, result: FoodAnalysisResult
    ) -> None:
        item.metadata["foodscope_relevant"] = result.relevant
        if not result.relevant:
            item.ai_score = 0.0
            item.ai_reason = "Not relevant to the food industry"
            item.ai_summary = item.title
            item.ai_tags = []
            if item.food is not None:
                item.food = item.food.model_copy(
                    update={
                        "importance_score": 0.0,
                        "profile_relevance_score": 0.0,
                        "opportunity_score": 0.0,
                        "evidence_quality_score": 0.0,
                        "risk_level": RiskLevel.NONE,
                        "risk_reason": "",
                        "event_key": None,
                        "product_launch": None,
                    }
                )
            return

        if item.food is None:
            raise ValueError(
                "FoodScope analysis requires a normalized source contract"
            )
        assert result.category is not None
        assert result.importance_score is not None
        assert result.profile_relevance_score is not None
        assert result.opportunity_score is not None
        assert result.evidence_quality_score is not None
        assert result.risk_level is not None
        event_key = result.event_key
        if not event_key:
            event_key = canonical_url_event_key(str(item.url))
            item.metadata["foodscope_event_key_source"] = (
                "canonical_url_fallback"
            )

        item.food = item.food.model_copy(
            update={
                "category": result.category,
                "markets": result.markets,
                "product_tags": result.product_tags,
                "ingredient_tags": result.ingredient_tags,
                "technology_tags": result.technology_tags,
                "company_tags": result.company_tags,
                "importance_score": result.importance_score,
                "profile_relevance_score": result.profile_relevance_score,
                "opportunity_score": result.opportunity_score,
                "evidence_quality_score": result.evidence_quality_score,
                "risk_level": result.risk_level,
                "risk_reason": result.risk_reason,
                "event_key": event_key,
                "sponsored": result.sponsored,
                "press_release": result.press_release,
                "product_launch": result.product_launch,
            }
        )
        item.ai_score = result.importance_score
        item.ai_reason = f"FoodScope category: {result.category.value}"
        item.ai_summary = result.summary_zh
        item.ai_tags = list(
            dict.fromkeys(
                result.product_tags
                + result.ingredient_tags
                + result.technology_tags
                + result.company_tags
            )
        )
        item.metadata["title_zh"] = result.title_zh
        item.metadata["summary_zh"] = result.summary_zh
