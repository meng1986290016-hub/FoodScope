"""Evidence admission rules for FoodScope intelligence."""

from __future__ import annotations

from dataclasses import dataclass

import tldextract

from src.models import ContentItem

from .models import EvidenceTier, FoodCategory


@dataclass(frozen=True)
class EvidenceDecision:
    """The deterministic evidence outcome for one item."""

    accepted: bool
    reason: str
    effective_tier: EvidenceTier


OFFICIAL_CATEGORIES = {
    FoodCategory.REGULATIONS_STANDARDS,
    FoodCategory.FOOD_SAFETY_RECALLS,
}

_EXTRACT_DOMAIN = tldextract.TLDExtract(suffix_list_urls=())


class EvidencePolicy:
    """Admit only items that meet category- and tier-specific evidence."""

    def evaluate(self, item: ContentItem) -> EvidenceDecision:
        food = item.food
        if food is None:
            return EvidenceDecision(
                accepted=False,
                reason="missing food analysis",
                effective_tier=EvidenceTier.WEAK_SIGNAL,
            )

        tier = food.evidence_tier
        if item.metadata.get("foodscope_isolated"):
            return EvidenceDecision(False, "isolated analysis", tier)
        if item.metadata.get("foodscope_relevant") is False:
            return EvidenceDecision(False, "not food-industry relevant", tier)

        if (
            food.category in OFFICIAL_CATEGORIES
            and not food.official_evidence_urls
        ):
            return EvidenceDecision(
                False, "official evidence required", tier
            )

        effective_tier = tier
        if tier in (EvidenceTier.PRIMARY, EvidenceTier.INDUSTRY):
            accepted = True
            reason = "accepted authoritative evidence"
        elif tier == EvidenceTier.DISCOVERY:
            accepted = bool(food.original_source_url) or (
                self._distinct_domains(food.evidence_urls) >= 2
            )
            reason = (
                "accepted corroborated discovery"
                if accepted
                else "discovery requires original source or two domains"
            )
        else:
            linked_tier = self._linked_tier(item)
            accepted = bool(food.original_source_url) and linked_tier in {
                EvidenceTier.PRIMARY,
                EvidenceTier.INDUSTRY,
                EvidenceTier.DISCOVERY,
            }
            if accepted and linked_tier is not None:
                effective_tier = linked_tier
                reason = "accepted linked weak signal"
            else:
                reason = (
                    "weak signal requires original source and linked evidence"
                )

        if accepted:
            self._apply_commercial_evidence_penalty(item)
        return EvidenceDecision(accepted, reason, effective_tier)

    @staticmethod
    def _linked_tier(item: ContentItem) -> EvidenceTier | None:
        raw_tier = item.metadata.get("linked_evidence_tier")
        if raw_tier is None:
            return None
        try:
            return EvidenceTier(int(raw_tier))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _distinct_domains(urls: list[str]) -> int:
        domains: set[str] = set()
        for url in urls:
            extracted = _EXTRACT_DOMAIN(url)
            registrable = extracted.top_domain_under_public_suffix
            if not registrable:
                registrable = extracted.domain
            if registrable:
                domains.add(registrable.lower())
        return len(domains)

    @staticmethod
    def _apply_commercial_evidence_penalty(item: ContentItem) -> None:
        food = item.food
        if food is None or not (food.sponsored or food.press_release):
            return
        if item.metadata.get("foodscope_evidence_penalty_applied"):
            return
        food.evidence_quality_score = max(
            0.0, food.evidence_quality_score - 2.0
        )
        item.metadata["foodscope_evidence_penalty_applied"] = True
