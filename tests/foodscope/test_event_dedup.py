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


def test_same_event_merges_when_market_metadata_is_inconsistent():
    france = analyzed_item("fr", "original fr", "M001")
    sweden = analyzed_item("se", "original se", "M002")
    assert france.food is not None
    assert sweden.food is not None
    france.metadata["title_zh"] = (
        "清洁标签趋势推动Dry4Good获投资扩产"
    )
    sweden.metadata["title_zh"] = (
        "Dry4Good天然原料产能扩张十倍"
    )
    france.food.markets = ["FR"]
    sweden.food.markets = ["SE"]
    for candidate in (france, sweden):
        assert candidate.food is not None
        candidate.food.company_tags = ["Dry4Good"]
        candidate.food.product_tags = ["天然原料", "清洁标签"]
    france.food.event_key = "dry4good|funding"
    sweden.food.event_key = "dry4good|capacity"

    assert len(merge_similar_food_events([france, sweden])) == 1


def test_same_event_merges_with_company_alias_and_shared_subject():
    full_brand = analyzed_item("one", "original one", "M001")
    short_brand = analyzed_item("two", "original two", "M002")
    assert full_brand.food is not None
    assert short_brand.food is not None
    full_brand.metadata["title_zh"] = (
        "大象清净园推出三款阿洛酮糖新品"
    )
    short_brand.metadata["title_zh"] = (
        "大青园推出低糖阿洛酮糖糖浆系列新品"
    )
    full_brand.food.markets = ["KR"]
    short_brand.food.markets = ["KR"]
    full_brand.food.company_tags = ["대상 청정원"]
    short_brand.food.company_tags = ["대상", "Cheongjungwon"]
    full_brand.food.ingredient_tags = ["阿洛酮糖"]
    short_brand.food.ingredient_tags = ["阿洛酮糖"]
    full_brand.food.event_key = "allulose|one"
    short_brand.food.event_key = "allulose|two"

    assert len(
        merge_similar_food_events([full_brand, short_brand])
    ) == 1


def test_same_financial_event_merges_without_subject_tags():
    first = analyzed_item("one", "original one", "M001")
    second = analyzed_item("two", "original two", "M002")
    assert first.food is not None
    assert second.food is not None
    for candidate in (first, second):
        assert candidate.food is not None
        candidate.metadata["title_zh"] = (
            "可口可乐2026年Q2业绩超预期并上调全年指引"
        )
        candidate.food.company_tags = ["The Coca-Cola Company"]
        candidate.food.product_tags = []
        candidate.food.ingredient_tags = []
        candidate.food.technology_tags = []
    first.food.event_key = "coke|q2|one"
    second.food.event_key = "coke|q2|two"

    assert len(merge_similar_food_events([first, second])) == 1


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


def test_event_fingerprint_filters_semantic_cross_day_duplicate(
    tmp_path,
):
    store = FoodEventFingerprintStore(
        tmp_path / "event-fingerprints.json"
    )
    prior = analyzed_item(
        "prior", "original prior", "M001"
    )
    current = analyzed_item(
        "current", "original current", "M002"
    )
    assert prior.food is not None
    assert current.food is not None
    for candidate in (prior, current):
        assert candidate.food is not None
        candidate.food.markets = ["US"]
        candidate.food.company_tags = ["Rootsii"]
        candidate.food.product_tags = ["红薯奶"]
    prior.metadata["title_zh"] = "美国红薯奶项目获资助"
    current.metadata["title_zh"] = "Rootsii红薯奶获得项目资金"
    prior.food.event_key = "rootsii|grant|one"
    current.food.event_key = "rootsii|funding|two"
    remembered_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    store.remember([prior], now=remembered_at)

    assert store.filter_new(
        [current],
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    ) == []
