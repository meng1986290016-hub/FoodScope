from datetime import datetime, timezone

from src.foodscope.event_dedup import (
    FoodEventFingerprintStore,
    merge_food_events,
    merge_similar_food_events,
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


def test_same_event_with_inconsistent_ai_keys_merges_semantically():
    rows = [
        (
            "M089",
            "乐天巧克力派印度年销售额突破1000亿韩元并扩建生产线",
            "Lotte Wellfood|Lotte India|production line expansion|IN|2026-07-27",
        ),
        (
            "M090",
            "乐天巧克力派印度第四条生产线投产，市场份额达70%",
            "Lotte Wellfood|LOTTE India|fourth production line commissioning|India|2026-07",
        ),
        (
            "M091",
            "乐天制果印度第四座巧克力派工厂投产，巩固市场首位地位",
            "Lotte Wellfood|production expansion|India|2026-07-27",
        ),
        (
            "M092",
            "乐天印度巧克力派第四生产线投产，年销售额突破千亿韩元",
            "lotte_wellfood|lotte_india|fourth_production_line_launch|in|2026-07-27",
        ),
    ]
    candidates = []
    for source_id, title_zh, event_key in rows:
        candidate = analyzed_item(
            source_id, f"original {source_id}", source_id
        )
        assert candidate.food is not None
        candidate.metadata["title_zh"] = title_zh
        candidate.food.event_key = event_key
        candidate.food.markets = ["IN", "KR"]
        candidate.food.company_tags = [
            "Lotte Wellfood",
            "LOTTE India",
        ]
        candidate.food.product_tags = [
            "chocolate_pie",
            "confectionery",
        ]
        candidates.append(candidate)

    merged = merge_similar_food_events(candidates)

    assert len(merged) == 1
    assert {
        source["source_id"]
        for source in merged[0].metadata["event_sources"]
    } == {"M089", "M090", "M091", "M092"}
    assert merged[0].food is not None
    assert len(merged[0].food.evidence_urls) == 4


def test_distinct_same_day_company_product_events_stay_separate():
    launch = analyzed_item(
        "launch",
        "original launch",
        "M089",
    )
    recycling = analyzed_item(
        "recycling",
        "original recycling",
        "M090",
    )
    for candidate in (launch, recycling):
        assert candidate.food is not None
        candidate.food.markets = ["IN"]
        candidate.food.company_tags = ["Lotte Wellfood"]
        candidate.food.product_tags = ["chocolate pie"]
    launch.metadata["title_zh"] = "乐天在印度推出草莓巧克力派新品"
    recycling.metadata["title_zh"] = (
        "乐天公布巧克力派包装材料回收计划"
    )
    launch.food.event_key = "launch"
    recycling.food.event_key = "recycling"

    merged = merge_similar_food_events([launch, recycling])

    assert len(merged) == 2


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
