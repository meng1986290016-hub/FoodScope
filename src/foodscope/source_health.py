"""Deterministic source-run metrics and 14-day recommendations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceRunMetric(BaseModel):
    source_id: str
    run_id: str
    fetch_status: Literal["success", "empty", "failure"]
    published_at_parse_rate: float = Field(ge=0, le=1)
    candidate_count: int = Field(ge=0)
    food_relevant_count: int = Field(ge=0)
    admitted_count: int = Field(ge=0)
    commercial_count: int = Field(ge=0)
    duplicate_event_count: int = Field(ge=0)
    unique_event_count: int = Field(ge=0)
    sponsored_count: int = Field(ge=0)
    access_mode: str
    ai_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)


CollectionTier = Literal["core", "extended", "discovery", "disable"]
AdapterMode = Literal[
    "direct_metadata", "metadata_or_query", "disabled"
]


class SourceTrialSummary(BaseModel):
    source_id: str
    run_count: int
    fetch_success_rate: float
    published_at_parse_rate: float
    candidate_count: int
    food_relevant_count: int
    admitted_count: int
    commercial_count: int
    duplicate_event_count: int
    unique_valid_events: int
    sponsored_count: int
    commercial_share: float
    duplicate_rate: float
    sponsored_share: float
    access_modes: list[str]
    ai_tokens: int
    estimated_cost: float
    recommended_collection_tier: CollectionTier
    recommended_adapter_mode: AdapterMode

    @classmethod
    def from_metrics(
        cls, metrics: list[SourceRunMetric]
    ) -> "SourceTrialSummary":
        if not metrics:
            raise ValueError("source trial requires at least one metric")
        source_ids = {metric.source_id for metric in metrics}
        if len(source_ids) != 1:
            raise ValueError(
                "source trial metrics must share one source_id"
            )

        run_count = len(metrics)
        successes = sum(
            metric.fetch_status in {"success", "empty"}
            for metric in metrics
        )
        fetch_success_rate = successes / run_count
        parse_rate = sum(
            metric.published_at_parse_rate for metric in metrics
        ) / run_count
        candidate_count = sum(
            metric.candidate_count for metric in metrics
        )
        relevant_count = sum(
            metric.food_relevant_count for metric in metrics
        )
        admitted_count = sum(
            metric.admitted_count for metric in metrics
        )
        commercial_count = sum(
            metric.commercial_count for metric in metrics
        )
        duplicate_count = sum(
            metric.duplicate_event_count for metric in metrics
        )
        unique_events = sum(
            metric.unique_event_count for metric in metrics
        )
        sponsored_count = sum(
            metric.sponsored_count for metric in metrics
        )
        access_modes = sorted(
            {metric.access_mode for metric in metrics}
        )
        tier = cls._recommend_tier(
            access_modes,
            fetch_success_rate,
            parse_rate,
            unique_events,
        )
        adapter_mode = cls._recommend_adapter_mode(
            access_modes, tier
        )
        return cls(
            source_id=next(iter(source_ids)),
            run_count=run_count,
            fetch_success_rate=fetch_success_rate,
            published_at_parse_rate=parse_rate,
            candidate_count=candidate_count,
            food_relevant_count=relevant_count,
            admitted_count=admitted_count,
            commercial_count=commercial_count,
            duplicate_event_count=duplicate_count,
            unique_valid_events=unique_events,
            sponsored_count=sponsored_count,
            commercial_share=(
                commercial_count / admitted_count
                if admitted_count
                else 0.0
            ),
            duplicate_rate=(
                duplicate_count / (duplicate_count + unique_events)
                if duplicate_count + unique_events
                else 0.0
            ),
            sponsored_share=(
                sponsored_count / admitted_count
                if admitted_count
                else 0.0
            ),
            access_modes=access_modes,
            ai_tokens=sum(metric.ai_tokens for metric in metrics),
            estimated_cost=sum(
                metric.estimated_cost for metric in metrics
            ),
            recommended_collection_tier=tier,
            recommended_adapter_mode=adapter_mode,
        )

    @staticmethod
    def _recommend_tier(
        access_modes: list[str],
        fetch_success_rate: float,
        parse_rate: float,
        unique_events: int,
    ) -> CollectionTier:
        if (
            {"robots_denied", "terms_denied"} & set(access_modes)
            or fetch_success_rate < 0.50
            or unique_events == 0
        ):
            return "disable"
        if (
            fetch_success_rate >= 0.90
            and parse_rate >= 0.90
            and unique_events >= 5
        ):
            return "core"
        if fetch_success_rate >= 0.70 and unique_events >= 2:
            return "extended"
        return "discovery"

    @staticmethod
    def _recommend_adapter_mode(
        access_modes: list[str], tier: CollectionTier
    ) -> AdapterMode:
        if tier == "disable":
            return "disabled"
        restricted = {
            "paywall",
            "login_required",
            "robots_denied",
            "terms_denied",
        }
        if restricted & set(access_modes):
            return "metadata_or_query"
        return "direct_metadata"


def summarize_metrics(
    metrics: list[SourceRunMetric],
) -> list[SourceTrialSummary]:
    grouped: dict[str, list[SourceRunMetric]] = {}
    for metric in metrics:
        grouped.setdefault(metric.source_id, []).append(metric)
    summaries = [
        SourceTrialSummary.from_metrics(group)
        for group in grouped.values()
    ]
    return sorted(
        summaries,
        key=lambda summary: (
            -summary.unique_valid_events,
            -summary.commercial_share,
            -summary.fetch_success_rate,
            summary.source_id,
        ),
    )
