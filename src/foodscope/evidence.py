"""Evidence admission rules for FoodScope intelligence."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Literal
from urllib.parse import urlsplit

import tldextract

from src.models import ContentItem

from .config import EvidenceConfig
from .models import EvidenceTier, FoodCategory


@dataclass(frozen=True)
class EvidenceDecision:
    """The deterministic evidence outcome for one item."""

    accepted: bool
    reason: str
    effective_tier: EvidenceTier


_ADMISSION_BUCKETS = {
    "accepted authoritative evidence": "accepted_authoritative",
    "accepted corroborated discovery": "accepted_corroborated",
    "accepted single attributable source": "accepted_single_source",
    "accepted attributable aggregator fallback": (
        "accepted_aggregator_fallback"
    ),
    "not food-industry relevant": "rejected_not_relevant",
    "official evidence required": (
        "rejected_official_evidence_required"
    ),
    "discovery publisher could not be identified": (
        "rejected_unknown_publisher"
    ),
    "discovery has no usable evidence URL": (
        "rejected_unknown_publisher"
    ),
    "discovery requires original source or two domains": (
        "rejected_strict_evidence"
    ),
}
_ADMISSION_COUNTERS = (
    "accepted_authoritative",
    "accepted_corroborated",
    "accepted_single_source",
    "accepted_aggregator_fallback",
    "rejected_not_relevant",
    "rejected_official_evidence_required",
    "rejected_unknown_publisher",
    "rejected_strict_evidence",
    "rejected_other",
)


def summarize_evidence_decisions(
    mode: Literal["loose", "strict"],
    decisions: list[EvidenceDecision],
) -> dict[str, str | int]:
    summary: dict[str, str | int] = {
        "mode": mode,
        **{key: 0 for key in _ADMISSION_COUNTERS},
    }
    for decision in decisions:
        key = _ADMISSION_BUCKETS.get(
            decision.reason, "rejected_other"
        )
        summary[key] = int(summary[key]) + 1
    return summary


OFFICIAL_CATEGORIES = {
    FoodCategory.REGULATIONS_STANDARDS,
    FoodCategory.FOOD_SAFETY_RECALLS,
}

_EXTRACT_DOMAIN = tldextract.TLDExtract(
    cache_dir=None,
    suffix_list_urls=(),
)


class EvidencePolicy:
    """Admit only items that meet category- and tier-specific evidence."""

    def __init__(self, config: EvidenceConfig | None = None):
        self.config = config or EvidenceConfig()

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

        if (
            food.category in OFFICIAL_CATEGORIES
            and not food.official_evidence_urls
        ):
            return EvidenceDecision(
                False, "official evidence required", tier
            )
        if item.metadata.get("foodscope_relevant") is False:
            return EvidenceDecision(False, "not food-industry relevant", tier)

        effective_tier = tier
        if tier in (EvidenceTier.PRIMARY, EvidenceTier.INDUSTRY):
            accepted = True
            reason = "accepted authoritative evidence"
        elif tier == EvidenceTier.DISCOVERY:
            accepted, reason = self._evaluate_discovery(item)
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

    def _evaluate_discovery(
        self, item: ContentItem
    ) -> tuple[bool, str]:
        food = item.food
        assert food is not None
        has_evidence = self._has_http_evidence(
            food.evidence_urls
        )
        valid_original = self._is_attributable_original(
            food.original_source_url
        )
        corroborated = self._distinct_domains(
            food.evidence_urls
        ) >= 2
        if self.config.mode == "strict":
            accepted = valid_original or corroborated
            return (
                accepted,
                (
                    "accepted corroborated discovery"
                    if accepted
                    else (
                        "discovery requires original source "
                        "or two domains"
                    )
                ),
            )
        if valid_original and has_evidence:
            return True, "accepted single attributable source"
        if corroborated:
            return True, "accepted corroborated discovery"
        publisher = str(
            item.metadata.get("discovered_source_name") or ""
        ).strip()
        if (
            self.config.allow_aggregator_fallback
            and publisher
            and self._has_aggregator_evidence(
                food.evidence_urls
            )
        ):
            return True, "accepted attributable aggregator fallback"
        if not publisher:
            return (
                False,
                "discovery publisher could not be identified",
            )
        return False, "discovery has no usable evidence URL"

    @staticmethod
    def _is_attributable_original(url: str | None) -> bool:
        if not url:
            return False
        parsed = urlsplit(str(url))
        hostname = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        normalized = hostname.lower().rstrip(".")
        if (
            normalized == "localhost"
            or normalized.endswith(".localhost")
            or normalized.endswith(".local")
            or normalized == "news.google.com"
        ):
            return False
        try:
            ipaddress.ip_address(normalized)
        except ValueError:
            extracted = _EXTRACT_DOMAIN(normalized)
            return bool(
                extracted.top_domain_under_public_suffix
            )
        return False

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
            parsed = urlsplit(str(url))
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
            ):
                continue
            extracted = _EXTRACT_DOMAIN(parsed.hostname)
            registrable = extracted.top_domain_under_public_suffix
            if not registrable:
                registrable = extracted.domain
            if registrable:
                domains.add(registrable.lower())
        return len(domains)

    @staticmethod
    def _has_http_evidence(urls: list[str]) -> bool:
        for url in urls:
            parsed = urlsplit(str(url))
            if (
                parsed.scheme in {"http", "https"}
                and parsed.hostname is not None
                and parsed.username is None
                and parsed.password is None
            ):
                return True
        return False

    @staticmethod
    def _has_aggregator_evidence(urls: list[str]) -> bool:
        return any(
            urlsplit(str(url)).scheme in {"http", "https"}
            and (
                urlsplit(str(url)).hostname or ""
            ).lower()
            == "news.google.com"
            for url in urls
        )

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
