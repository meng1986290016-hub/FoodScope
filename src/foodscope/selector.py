"""Deterministic, profile-aware FoodScope brief selection."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import median

from pydantic import BaseModel, Field

from src.models import ContentItem

from .config import BriefProfile
from .evidence import EvidenceDecision, EvidencePolicy
from .models import FoodCategory, RiskLevel


class SelectionResult(BaseModel):
    """Canonical snapshot of one profile selection."""

    items: list[ContentItem]
    risk_alerts: list[ContentItem] = Field(default_factory=list)
    rejected: list[ContentItem] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)


@dataclass(frozen=True)
class _RankedItem:
    item: ContentItem
    evidence: EvidenceDecision
    base_rank: float
    topic_multiplier: float
    market_multiplier: float
    final_rank: float


_RISK_ORDER = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.SEVERE: 4,
}

_COMMERCIAL_CATEGORIES = {
    FoodCategory.PRODUCT_INNOVATION,
    FoodCategory.INGREDIENTS_TECHNOLOGY,
    FoodCategory.PACKAGING_LABELING,
    FoodCategory.CONSUMER_TRENDS,
    FoodCategory.RETAIL_FOODSERVICE,
    FoodCategory.COMPANY_UPDATES,
}


class FoodProfileSelector:
    """Select a diverse brief after applying evidence admission."""

    def __init__(
        self, evidence_policy: EvidencePolicy | None = None
    ) -> None:
        self.evidence_policy = evidence_policy or EvidencePolicy()

    def select(
        self, items: list[ContentItem], profile: BriefProfile
    ) -> SelectionResult:
        ranked: list[_RankedItem] = []
        rejected: list[ContentItem] = []
        risk_alerts: list[_RankedItem] = []

        for item in items:
            decision = self.evidence_policy.evaluate(item)
            if not decision.accepted or item.food is None:
                rejected.append(item)
                continue
            candidate = self._rank(item, profile, decision)
            self._save_reason(candidate, profile)
            if self._is_risk_alert(item, profile):
                risk_alerts.append(candidate)
            elif candidate.base_rank < profile.minimum_score:
                rejected.append(item)
            else:
                ranked.append(candidate)

        ranked.sort(key=self._sort_key)
        risk_alerts.sort(key=self._sort_key)
        selected = self._select_regular(ranked, profile)
        if profile.id == "balanced" and profile.commercial_min_ratio:
            selected = self._enforce_commercial_mix(
                selected, ranked, profile
            )
        selected.sort(key=self._sort_key)

        selected_ids = {id(candidate.item) for candidate in selected}
        rejected.extend(
            candidate.item
            for candidate in ranked
            if id(candidate.item) not in selected_ids
        )
        selected_items = [candidate.item for candidate in selected]
        category_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for item in selected_items:
            food = item.food
            assert food is not None
            category_counts[food.category.value] = (
                category_counts.get(food.category.value, 0) + 1
            )
            source_counts[food.source_id] = (
                source_counts.get(food.source_id, 0) + 1
            )

        return SelectionResult(
            items=selected_items,
            risk_alerts=[candidate.item for candidate in risk_alerts],
            rejected=rejected,
            category_counts=category_counts,
            source_counts=source_counts,
        )

    @staticmethod
    def _rank(
        item: ContentItem,
        profile: BriefProfile,
        evidence: EvidenceDecision,
    ) -> _RankedItem:
        food = item.food
        assert food is not None
        base_rank = (
            0.45 * food.importance_score
            + 0.25 * food.profile_relevance_score
            + 0.20 * food.opportunity_score
            + 0.10 * food.evidence_quality_score
        )
        topic_multiplier = 1.0 + profile.topic_weights[food.category]
        market_boost = max(
            (
                profile.market_weights.get(market, 0.0)
                for market in food.markets
            ),
            default=0.0,
        )
        unique_markets = set(food.markets)
        market_penalty = (
            sum(
                profile.market_penalties.get(market, 0.0)
                for market in unique_markets
            )
            / len(unique_markets)
            if unique_markets
            else 0.0
        )
        market_multiplier = (1.0 + market_boost) * (
            1.0 - market_penalty
        )
        return _RankedItem(
            item=item,
            evidence=evidence,
            base_rank=base_rank,
            topic_multiplier=topic_multiplier,
            market_multiplier=market_multiplier,
            final_rank=(
                base_rank * topic_multiplier * market_multiplier
            ),
        )

    @staticmethod
    def _sort_key(candidate: _RankedItem) -> tuple:
        return (
            -candidate.final_rank,
            int(candidate.evidence.effective_tier),
            -candidate.item.published_at.timestamp(),
            str(candidate.item.url),
        )

    @staticmethod
    def _is_risk_alert(
        item: ContentItem, profile: BriefProfile
    ) -> bool:
        food = item.food
        assert food is not None
        return (
            _RISK_ORDER[food.risk_level]
            >= _RISK_ORDER[profile.risk_override_min]
        )

    def _select_regular(
        self,
        ranked: list[_RankedItem],
        profile: BriefProfile,
    ) -> list[_RankedItem]:
        if not ranked:
            return []
        low_priority_cutoff = median(profile.topic_weights.values())
        exploration: list[_RankedItem] = []
        for candidate in ranked:
            food = candidate.item.food
            assert food is not None
            if (
                profile.topic_weights[food.category]
                < low_priority_cutoff
            ):
                exploration.append(candidate)
        selected: list[_RankedItem] = []
        selected_ids: set[int] = set()
        source_counts: dict[str, int] = {}

        def add(candidate: _RankedItem) -> bool:
            food = candidate.item.food
            assert food is not None
            if id(candidate.item) in selected_ids:
                return False
            if source_counts.get(food.source_id, 0) >= profile.max_per_source:
                return False
            selected.append(candidate)
            selected_ids.add(id(candidate.item))
            source_counts[food.source_id] = (
                source_counts.get(food.source_id, 0) + 1
            )
            return True

        exploration_added = 0
        for candidate in exploration:
            if (
                exploration_added >= profile.exploration_slots
                or len(selected) >= profile.max_items
            ):
                break
            if add(candidate):
                exploration_added += 1

        for candidate in ranked:
            if len(selected) >= profile.max_items:
                break
            add(candidate)
        return selected

    def _enforce_commercial_mix(
        self,
        selected: list[_RankedItem],
        ranked: list[_RankedItem],
        profile: BriefProfile,
    ) -> list[_RankedItem]:
        target = ceil(len(selected) * profile.commercial_min_ratio)
        admitted_commercial = [
            candidate
            for candidate in ranked
            if self._is_commercial(candidate)
        ]
        if len(admitted_commercial) < target:
            return selected

        current = sum(self._is_commercial(item) for item in selected)
        if current >= target:
            return selected

        selected_ids = {id(candidate.item) for candidate in selected}
        replacements = [
            candidate
            for candidate in admitted_commercial
            if id(candidate.item) not in selected_ids
        ]
        noncommercial = sorted(
            (
                candidate
                for candidate in selected
                if not self._is_commercial(candidate)
            ),
            key=self._sort_key,
            reverse=True,
        )
        source_counts = self._source_counts(selected)

        for replacement in replacements:
            if current >= target:
                break
            replacement_food = replacement.item.food
            assert replacement_food is not None
            for displaced in list(noncommercial):
                displaced_food = displaced.item.food
                assert displaced_food is not None
                source_count = source_counts.get(
                    replacement_food.source_id, 0
                )
                if (
                    replacement_food.source_id
                    == displaced_food.source_id
                ):
                    source_count -= 1
                if source_count >= profile.max_per_source:
                    continue
                selected.remove(displaced)
                selected.append(replacement)
                noncommercial.remove(displaced)
                source_counts[displaced_food.source_id] -= 1
                source_counts[replacement_food.source_id] = (
                    source_counts.get(replacement_food.source_id, 0) + 1
                )
                current += 1
                break
        return selected

    @staticmethod
    def _is_commercial(candidate: _RankedItem) -> bool:
        food = candidate.item.food
        assert food is not None
        return food.category in _COMMERCIAL_CATEGORIES

    @staticmethod
    def _source_counts(
        candidates: list[_RankedItem],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for candidate in candidates:
            food = candidate.item.food
            assert food is not None
            counts[food.source_id] = counts.get(food.source_id, 0) + 1
        return counts

    @staticmethod
    def _save_reason(
        candidate: _RankedItem, profile: BriefProfile
    ) -> None:
        food = candidate.item.food
        assert food is not None
        candidate.item.metadata["foodscope_base_score"] = round(
            candidate.base_rank, 4
        )
        candidate.item.metadata["foodscope_final_score"] = round(
            candidate.final_rank, 4
        )
        food.selection_reason = (
            f"profile={profile.id}; "
            f"importance={food.importance_score:.2f}; "
            f"profile_relevance={food.profile_relevance_score:.2f}; "
            f"opportunity={food.opportunity_score:.2f}; "
            f"evidence_quality={food.evidence_quality_score:.2f}; "
            f"topic_multiplier={candidate.topic_multiplier:.4f}; "
            f"market_multiplier={candidate.market_multiplier:.4f}; "
            f"evidence_tier={int(candidate.evidence.effective_tier)}; "
            f"final_rank={candidate.final_rank:.4f}"
        )
