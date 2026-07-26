from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.foodscope.evidence import (
    EvidencePolicy,
    summarize_evidence_decisions,
)
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
    discovered_source_name: str | None = None,
) -> ContentItem:
    return ContentItem(
        id="food:evidence:test",
        source_type=SourceType.FOOD,
        title="Evidence test",
        url="https://publisher.example/story",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        metadata={
            "discovered_source_name": discovered_source_name,
        },
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


def test_loose_mode_accepts_attributable_single_source_discovery():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=["https://news.google.com/rss/articles/one"],
        discovered_source_name="Food Business News",
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode="loose",
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is True
    assert decision.reason == "accepted attributable aggregator fallback"


def test_strict_mode_rejects_attributable_single_source_discovery():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=["https://news.google.com/rss/articles/one"],
        discovered_source_name="Food Business News",
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode="strict",
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is False
    assert decision.reason == (
        "discovery requires original source or two domains"
    )


def test_loose_mode_rejects_unattributable_aggregator_result():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=["https://news.google.com/rss/articles/one"],
        discovered_source_name=None,
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode="loose",
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is False
    assert decision.reason == "discovery publisher could not be identified"


def test_loose_mode_rejects_invalid_original_and_missing_evidence():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url="not-a-url",
        evidence_urls=[],
        discovered_source_name="Publisher",
    )

    decision = EvidencePolicy().evaluate(item)

    assert decision.accepted is False
    assert decision.reason == "discovery has no usable evidence URL"


def test_loose_mode_rejects_malformed_and_private_evidence_urls():
    malformed = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=["https://"],
        discovered_source_name="Publisher",
    )
    private = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url="http://127.0.0.1/story",
        evidence_urls=["http://127.0.0.1/story"],
        discovered_source_name="Publisher",
    )

    assert EvidencePolicy().evaluate(malformed).accepted is False
    assert EvidencePolicy().evaluate(private).accepted is False


def test_strict_mode_accepts_valid_original_without_evidence_urls():
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url="https://publisher.example.com/story",
        evidence_urls=[],
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode="strict",
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is True
    assert decision.reason == "accepted corroborated discovery"


@pytest.mark.parametrize("mode", ["loose", "strict"])
def test_discovery_does_not_count_non_http_domains(mode):
    item = evidence_item(
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url=None,
        evidence_urls=[
            "ftp://one.example.com/a",
            "ftp://two.test.net/b",
        ],
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode=mode,
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is False


@pytest.mark.parametrize("mode", ["loose", "strict"])
@pytest.mark.parametrize(
    "category",
    [
        FoodCategory.REGULATIONS_STANDARDS,
        FoodCategory.FOOD_SAFETY_RECALLS,
    ],
)
def test_official_categories_always_require_official_evidence(
    mode, category
):
    item = evidence_item(
        category=category,
        evidence_tier=EvidenceTier.DISCOVERY,
        original_source_url="https://publisher.example/story",
        official_evidence_urls=[],
        discovered_source_name="Publisher",
    )

    decision = EvidencePolicy(
        SimpleNamespace(
            mode=mode,
            allow_aggregator_fallback=True,
        )
    ).evaluate(item)

    assert decision.accepted is False
    assert decision.reason == "official evidence required"


def test_missing_official_evidence_precedes_relevance_rejection():
    item = evidence_item(
        category=FoodCategory.REGULATIONS_STANDARDS,
        official_evidence_urls=[],
    )
    item.metadata["foodscope_relevant"] = False

    decision = EvidencePolicy().evaluate(item)

    assert decision.accepted is False
    assert decision.reason == "official evidence required"


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


def test_evidence_decisions_have_stable_manifest_buckets():
    authoritative = EvidencePolicy().evaluate(evidence_item())
    fallback = EvidencePolicy().evaluate(
        evidence_item(
            evidence_tier=EvidenceTier.DISCOVERY,
            original_source_url=None,
            evidence_urls=[
                "https://news.google.com/rss/articles/one"
            ],
            discovered_source_name="Publisher",
        )
    )
    official_rejection = EvidencePolicy().evaluate(
        evidence_item(
            category=FoodCategory.FOOD_SAFETY_RECALLS,
            official_evidence_urls=[],
        )
    )

    summary = summarize_evidence_decisions(
        "loose",
        [authoritative, fallback, official_rejection],
    )

    assert summary == {
        "mode": "loose",
        "accepted_authoritative": 1,
        "accepted_corroborated": 0,
        "accepted_single_source": 0,
        "accepted_aggregator_fallback": 1,
        "rejected_not_relevant": 0,
        "rejected_official_evidence_required": 1,
        "rejected_unknown_publisher": 0,
        "rejected_strict_evidence": 0,
        "rejected_other": 0,
    }
