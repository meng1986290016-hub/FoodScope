from datetime import datetime, timezone

from src.foodscope.event_dedup import (
    FoodEventFingerprintStore,
    merge_food_events,
)
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    FoodIntelligence,
    RiskLevel,
)
from src.models import ContentItem
from tests.foodscope.test_normalizer import item


def analyzed_item(
    item_id: str,
    title: str,
    source_id: str,
    *,
    evidence_tier: EvidenceTier = EvidenceTier.INDUSTRY,
) -> ContentItem:
    candidate = item(item_id, title)
    candidate.food = FoodIntelligence(
        category=FoodCategory.PRODUCT_INNOVATION,
        markets=["JP"],
        importance_score=8,
        profile_relevance_score=8,
        opportunity_score=7,
        evidence_quality_score=8,
        risk_level=RiskLevel.NONE,
        evidence_tier=evidence_tier,
        collection_tier=CollectionTier.CORE,
        event_key="example|protein-tea|launch|JP|2026-07-24",
        source_id=source_id,
        official_evidence_urls=(
            [f"https://example.com/{item_id}"]
            if evidence_tier == EvidenceTier.PRIMARY
            else []
        ),
    )
    return candidate


def test_cross_language_items_with_same_event_key_merge():
    english = analyzed_item(
        "en", "Example launches Protein Tea in Japan", "M001"
    )
    japanese = analyzed_item(
        "ja", "Example、日本でプロテインティーを発売", "M075"
    )

    merged = merge_food_events([english, japanese])

    assert len(merged) == 1
    assert {
        link["source_id"] for link in merged[0].metadata["event_sources"]
    } == {"M001", "M075"}


def test_primary_evidence_survives_event_merge():
    industry = analyzed_item("media", "Media report", "M001")
    official = analyzed_item(
        "official",
        "Official report",
        "global_codex_news",
        evidence_tier=EvidenceTier.PRIMARY,
    )

    merged = merge_food_events([industry, official])

    assert merged[0].food is not None
    assert merged[0].food.source_id == "global_codex_news"
    assert merged[0].food.official_evidence_urls == [
        "https://example.com/official"
    ]


def test_event_fingerprint_expires_after_seven_days(tmp_path):
    store = FoodEventFingerprintStore(
        tmp_path / "event-fingerprints.json"
    )
    prior = analyzed_item(
        "old", "Example launches Protein Tea in Japan", "M001"
    )
    remembered_at = datetime(2026, 7, 24, tzinfo=timezone.utc)
    store.remember([prior], now=remembered_at)

    assert store.filter_new(
        [prior], now=datetime(2026, 7, 30, tzinfo=timezone.utc)
    ) == []
    assert store.filter_new(
        [prior], now=datetime(2026, 8, 1, tzinfo=timezone.utc)
    ) == [prior]
