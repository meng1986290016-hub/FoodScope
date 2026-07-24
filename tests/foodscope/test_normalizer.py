from datetime import datetime, timezone

from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
)
from src.foodscope.normalizer import normalize_item
from src.models import ContentItem, SourceType


def item(item_id: str, title: str) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.FOOD,
        title=title,
        url=f"https://example.com/{item_id}",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def test_normalizer_attaches_source_contract():
    source = FoodSourceSpec(
        id="M001",
        name="FoodNavigator",
        url="https://example.com",
        adapter="rss",
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        packs=["global_industry", "product_launches"],
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )

    normalized = normalize_item(item("one", "  New   drink  "), source)

    assert normalized.title == "New drink"
    assert normalized.food is not None
    assert normalized.food.source_id == "M001"
    assert normalized.food.original_source_url == "https://example.com/one"
    assert normalized.metadata["source_name"] == "FoodNavigator"


def test_primary_source_url_becomes_official_evidence():
    source = FoodSourceSpec(
        id="us_fda_food_recalls",
        name="FDA Food Recalls",
        url="https://www.fda.gov/",
        adapter="rss",
        evidence_tier=EvidenceTier.PRIMARY,
        collection_tier=CollectionTier.CORE,
        categories=[FoodCategory.FOOD_SAFETY_RECALLS],
    )

    normalized = normalize_item(item("recall", "Recall notice"), source)

    assert normalized.food is not None
    assert normalized.food.official_evidence_urls == [
        "https://example.com/recall"
    ]


def test_discovery_aggregator_is_not_treated_as_original_source():
    source = FoodSourceSpec(
        id="en_product_launch",
        name="English product launches",
        url="https://news.google.com/",
        adapter="discovery_query",
        evidence_tier=EvidenceTier.DISCOVERY,
        collection_tier=CollectionTier.DISCOVERY,
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )

    normalized = normalize_item(item("query", "Launch signal"), source)

    assert normalized.food is not None
    assert normalized.food.original_source_url is None
