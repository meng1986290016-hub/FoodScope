"""Deterministic source-run metrics and 14-day recommendations."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field


class SourceRunMetric(BaseModel):
    source_id: str
    run_id: str
    observed_date: date | None = None
    run_provenance: Literal["manual", "scheduled"] = "manual"
    fetch_status: Literal[
        "success", "empty", "failure", "skipped_rotation"
    ]
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
    estimated_cost: float | None = Field(default=None, ge=0)


CollectionTier = Literal[
    "core", "extended", "discovery", "disable", "pending"
]
AdapterMode = Literal[
    "direct_metadata", "metadata_or_query", "disabled", "pending"
]


class SourceTrialSummary(BaseModel):
    source_id: str
    run_count: int
    trial_day_count: int
    consecutive_day_count: int
    attempt_day_count: int
    trial_status: Literal["provisional", "complete"]
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
    estimated_cost: float | None
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

        scheduled_dates = sorted(
            {
                metric.observed_date
                for metric in metrics
                if metric.run_provenance == "scheduled"
                and metric.observed_date is not None
            }
        )
        trial_day_count = len(scheduled_dates)
        consecutive_dates = cls._longest_consecutive_dates(
            scheduled_dates
        )
        consecutive_day_count = len(consecutive_dates)
        candidate_window = set(consecutive_dates[-14:])
        attempt_day_count = len(
            {
                metric.observed_date
                for metric in metrics
                if metric.run_provenance == "scheduled"
                and metric.observed_date in candidate_window
                and metric.fetch_status != "skipped_rotation"
            }
        )
        trial_status: Literal["provisional", "complete"] = (
            "complete"
            if (
                consecutive_day_count >= 14
                and attempt_day_count >= 4
            )
            else "provisional"
        )
        if trial_status == "complete":
            evaluation_dates = set(consecutive_dates[-14:])
            evaluation_metrics = [
                metric
                for metric in metrics
                if metric.run_provenance == "scheduled"
                and metric.observed_date in evaluation_dates
                and metric.fetch_status != "skipped_rotation"
            ]
        else:
            scheduled_metrics = [
                metric
                for metric in metrics
                if metric.run_provenance == "scheduled"
                and metric.fetch_status != "skipped_rotation"
            ]
            manual_metrics = [
                metric
                for metric in metrics
                if metric.run_provenance == "manual"
                and metric.fetch_status != "skipped_rotation"
            ]
            evaluation_metrics = (
                scheduled_metrics or manual_metrics
            )
        run_count = len(evaluation_metrics)
        successes = sum(
            metric.fetch_status in {"success", "empty"}
            for metric in evaluation_metrics
        )
        fetch_success_rate = (
            successes / run_count if run_count else 0.0
        )
        parse_rate = sum(
            metric.published_at_parse_rate
            for metric in evaluation_metrics
        ) / run_count if run_count else 0.0
        candidate_count = sum(
            metric.candidate_count
            for metric in evaluation_metrics
        )
        relevant_count = sum(
            metric.food_relevant_count
            for metric in evaluation_metrics
        )
        admitted_count = sum(
            metric.admitted_count
            for metric in evaluation_metrics
        )
        commercial_count = sum(
            metric.commercial_count
            for metric in evaluation_metrics
        )
        duplicate_count = sum(
            metric.duplicate_event_count
            for metric in evaluation_metrics
        )
        unique_events = sum(
            metric.unique_event_count
            for metric in evaluation_metrics
        )
        sponsored_count = sum(
            metric.sponsored_count
            for metric in evaluation_metrics
        )
        access_modes = sorted(
            {
                metric.access_mode
                for metric in evaluation_metrics
            }
        )
        if trial_status == "complete":
            tier = cls._recommend_tier(
                access_modes,
                fetch_success_rate,
                parse_rate,
                unique_events,
            )
            adapter_mode = cls._recommend_adapter_mode(
                access_modes, tier
            )
        else:
            tier = "pending"
            adapter_mode = "pending"
        return cls(
            source_id=next(iter(source_ids)),
            run_count=run_count,
            trial_day_count=trial_day_count,
            consecutive_day_count=consecutive_day_count,
            attempt_day_count=attempt_day_count,
            trial_status=trial_status,
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
            ai_tokens=sum(
                metric.ai_tokens for metric in evaluation_metrics
            ),
            estimated_cost=(
                None
                if any(
                    metric.estimated_cost is None
                    for metric in evaluation_metrics
                )
                else sum(
                    metric.estimated_cost or 0.0
                    for metric in evaluation_metrics
                )
            ),
            recommended_collection_tier=tier,
            recommended_adapter_mode=adapter_mode,
        )

    @staticmethod
    def _longest_consecutive_dates(
        dates: list[date],
    ) -> list[date]:
        longest: list[date] = []
        current: list[date] = []
        for observed in dates:
            if (
                current
                and observed != current[-1] + timedelta(days=1)
            ):
                if len(current) >= len(longest):
                    longest = current
                current = []
            current.append(observed)
        if len(current) >= len(longest):
            longest = current
        return longest

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
        if tier == "pending":
            return "pending"
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
