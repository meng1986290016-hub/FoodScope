from datetime import datetime, timezone

from src.foodscope.evidence import EvidencePolicy
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    FoodIntelligence,
    RiskLevel,
)
from src.models import ContentItem, SourceType


def evidence_item(
    *,
    category: FoodCategory = FoodCategory.PRODUCT_INNOVATION,
    evidence_tier: EvidenceTier = EvidenceTier.INDUSTRY,
    original_source_url: str | None = "https://publisher.example/story",
    evidence_urls: list[str] | None = None,
    official_evidence_urls: list[str] | None = None,
    sponsored: bool = False,
    press_release: bool = False,
) -> ContentItem:
    return ContentItem(
        id="food:evidence:test",
        source_type=SourceType.FOOD,
        title="Evidence test",
        url="https://publisher.example/story",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        food=FoodIntelligence(
            category=category,
            importance_score=8,
            profile_relevance_score=8,
            opportunity_score=8,
            evidence_quality_score=8,
            risk_level=RiskLevel.NONE,
            evidence_tier=evidence_tier,
            collection_tier=CollectionTier.CORE,
            source_id="test",
            original_source_url=original_source_url,
            evidence_urls=evidence_urls
            if evidence_urls is not None
            else ["https://publisher.example/story"],
            official_evidence_urls=official_evidence_urls or [],
            sponsored=sponsored,
            press_release=press_release,
        ),
    )


def test_safety_item_without_official_url_is_rejected():
    item = evidence_item(
        category=FoodCategory.FOOD_SAFETY_RECALLS,
        evidence_tier=EvidenceTier.PRIMARY,
        official_evidence_urls=[],
    )

    decision = EvidencePolicy().evaluate(item)

    assert decision.accepted is False
    assert decision.reason == "official evidence required"


def test_official_category_is_accepted_with_official_url():
    item = evidence_item(
        category=FoodCategory.REGULATIONS_STANDARDS,
        evidence_tier=EvidenceTier.PRIMARY,
        official_evidence_urls=["https://fda.gov/rule"],
    )

    assert EvidencePolicy().evaluate(item).accepted is True


def test_tier_three_item_requires_primary_or_two_independent_domains():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=["https://one.example/a"],
    )

    assert EvidencePolicy().evaluate(item).accepted is False

    item.food.evidence_urls = [
        "https://news.example/a",
        "https://analysis.example/b",
    ]
    assert EvidencePolicy().evaluate(item).accepted is False

    item.food.evidence_urls.append("https://independent.test/c")
    assert EvidencePolicy().evaluate(item).accepted is True


def test_tier_four_requires_linked_evidence_and_original_url():
    item = evidence_item(
        evidence_tier=EvidenceTier.WEAK_SIGNAL,
        original_source_url=None,
    )
    item.metadata["linked_evidence_tier"] = 2

    assert EvidencePolicy().evaluate(item).accepted is False

    item.food.original_source_url = "https://publisher.example/original"
    decision = EvidencePolicy().evaluate(item)
    assert decision.accepted is True
    assert decision.effective_tier == EvidenceTier.INDUSTRY


def test_isolated_item_is_rejected():
    item = evidence_item()
    item.metadata["foodscope_isolated"] = True

    assert EvidencePolicy().evaluate(item).reason == "isolated analysis"


def test_sponsored_or_press_release_material_loses_evidence_score():
    sponsored = evidence_item(sponsored=True)
    release = evidence_item(press_release=True)

    EvidencePolicy().evaluate(sponsored)
    EvidencePolicy().evaluate(release)

    assert sponsored.food.evidence_quality_score == 6
    assert release.food.evidence_quality_score == 6
