from datetime import datetime, timedelta, timezone

from src.foodscope.config import BriefProfile, FoodScopeConfig
from src.foodscope.loaders import load_profile
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    FoodIntelligence,
    RiskLevel,
)
from src.foodscope.selector import FoodProfileSelector
from src.models import ContentItem, SourceType


NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def scored_item(
    item_id: str,
    *,
    source_id: str | None = None,
    category: FoodCategory = FoodCategory.PRODUCT_INNOVATION,
    collection_tier: CollectionTier = CollectionTier.CORE,
    evidence_tier: EvidenceTier = EvidenceTier.INDUSTRY,
    importance: float = 8,
    relevance: float | None = None,
    opportunity: float | None = None,
    evidence: float | None = None,
    risk_level: RiskLevel = RiskLevel.NONE,
    published_offset: int = 0,
) -> ContentItem:
    source_id = source_id or item_id
    return ContentItem(
        id=f"food:{item_id}",
        source_type=SourceType.FOOD,
        title=item_id,
        url=f"https://{item_id}.example/story",
        published_at=NOW - timedelta(hours=published_offset),
        food=FoodIntelligence(
            category=category,
            importance_score=importance,
            profile_relevance_score=(
                importance if relevance is None else relevance
            ),
            opportunity_score=(
                importance if opportunity is None else opportunity
            ),
            evidence_quality_score=(
                importance if evidence is None else evidence
            ),
            risk_level=risk_level,
            evidence_tier=evidence_tier,
            collection_tier=collection_tier,
            source_id=source_id,
            original_source_url=f"https://{item_id}.example/story",
            evidence_urls=[f"https://{item_id}.example/story"],
        ),
    )


def profile(
    profile_id: str = "balanced",
    **updates,
) -> BriefProfile:
    loaded = load_profile(FoodScopeConfig(profile=profile_id))
    return loaded.model_copy(update=updates)


def test_high_risk_is_alert_but_does_not_consume_regular_quota():
    alert = scored_item("alert", risk_level=RiskLevel.HIGH)
    market = scored_item(
        "market", category=FoodCategory.CONSUMER_TRENDS
    )

    result = FoodProfileSelector().select(
        [alert, market], profile("market")
    )

    assert result.risk_alerts == [alert]
    assert result.items == [market]


def test_collection_tier_does_not_change_rank():
    core = scored_item(
        "core",
        source_id="A",
        collection_tier=CollectionTier.CORE,
        importance=7,
    )
    extended = scored_item(
        "extended",
        source_id="B",
        collection_tier=CollectionTier.EXTENDED,
        importance=8,
    )

    result = FoodProfileSelector().select(
        [core, extended], profile("balanced", exploration_slots=0)
    )

    assert result.items[0].food.source_id == "B"
    assert "collection" not in result.items[0].food.selection_reason


def test_base_rank_controls_minimum_score_gate():
    inflated_by_topic = scored_item(
        "below",
        category=FoodCategory.PRODUCT_INNOVATION,
        importance=5.9,
    )

    result = FoodProfileSelector().select(
        [inflated_by_topic], profile("new_products", minimum_score=6.0)
    )

    assert result.items == []
    assert result.rejected == [inflated_by_topic]


def test_source_cap_and_tie_breakers_are_deterministic():
    items = [
        scored_item(
            f"same-{index}",
            source_id="same",
            evidence_tier=EvidenceTier.INDUSTRY,
            published_offset=index,
        )
        for index in range(4)
    ]
    stronger = scored_item(
        "primary",
        source_id="other",
        evidence_tier=EvidenceTier.PRIMARY,
        published_offset=10,
    )

    result = FoodProfileSelector().select(
        items + [stronger],
        profile("balanced", exploration_slots=0, max_per_source=2),
    )

    assert result.items[0] == stronger
    assert result.source_counts["same"] == 2
    assert [item.id for item in result.items[1:]] == [
        "food:same-0",
        "food:same-1",
    ]


def test_exploration_slot_includes_low_priority_category():
    high = [
        scored_item(f"innovation-{index}", importance=9 - index / 10)
        for index in range(15)
    ]
    exploration = scored_item(
        "regulation",
        category=FoodCategory.REGULATIONS_STANDARDS,
        evidence_tier=EvidenceTier.PRIMARY,
        importance=6.1,
    )
    exploration.food.official_evidence_urls = [
        "https://regulation.example/official"
    ]

    result = FoodProfileSelector().select(
        high + [exploration],
        profile(
            "new_products",
            exploration_slots=1,
            max_items=15,
            max_per_source=2,
        ),
    )

    assert exploration in result.items
    assert len(result.items) == 15


def test_balanced_profile_enforces_commercial_mix_when_pool_allows():
    noncommercial = [
        scored_item(
            f"reg-{index}",
            category=FoodCategory.REGULATIONS_STANDARDS,
            evidence_tier=EvidenceTier.PRIMARY,
            importance=10,
        )
        for index in range(6)
    ]
    for item in noncommercial:
        item.food.official_evidence_urls = [str(item.url)]
    commercial = [
        scored_item(f"commercial-{index}", importance=6.1)
        for index in range(12)
    ]

    result = FoodProfileSelector().select(
        noncommercial + commercial,
        profile(
            "balanced",
            exploration_slots=0,
            max_items=15,
            max_per_source=2,
        ),
    )

    commercial_categories = {
        FoodCategory.PRODUCT_INNOVATION,
        FoodCategory.INGREDIENTS_TECHNOLOGY,
        FoodCategory.PACKAGING_LABELING,
        FoodCategory.CONSUMER_TRENDS,
        FoodCategory.RETAIL_FOODSERVICE,
        FoodCategory.COMPANY_UPDATES,
    }
    commercial_count = sum(
        item.food.category in commercial_categories for item in result.items
    )
    assert len(result.items) == 15
    assert commercial_count >= 11


def test_selection_reason_and_counts_capture_rank_inputs():
    item = scored_item("ranked", importance=8)

    result = FoodProfileSelector().select(
        [item], profile("market", exploration_slots=0)
    )

    assert result.category_counts == {"product_innovation": 1}
    assert result.source_counts == {"ranked": 1}
    assert "profile=market" in item.food.selection_reason
    assert "importance=8.00" in item.food.selection_reason
    assert "final_rank=" in item.food.selection_reason
