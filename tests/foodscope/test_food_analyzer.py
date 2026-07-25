import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from src.ai.client import AIClient
from src.foodscope.analyzer import FoodContentAnalyzer
from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
)
from src.foodscope.normalizer import normalize_item
from src.models import ContentItem, SourceType


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "foodscope"


class StubClient(AIClient):
    def __init__(self, responses: list[str | Exception]):
        self.responses = deque(responses)
        self.calls = 0

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


def _response() -> str:
    return (FIXTURE_DIR / "analysis_response.json").read_text()


def _item(item_id: str = "launch") -> ContentItem:
    item = ContentItem(
        id=item_id,
        source_type=SourceType.FOOD,
        title="Example launches Protein Tea in Japan",
        url=f"https://example.com/{item_id}",
        content="A high-protein ready-to-drink tea launches in Japanese retail.",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    source = FoodSourceSpec(
        id="M001",
        name="Food Industry News",
        url="https://example.com",
        adapter="rss",
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        packs=["global_industry", "product_launches"],
        markets=["JP"],
        languages=["en"],
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )
    return normalize_item(item, source)


def test_valid_response_populates_food_dimensions_and_product_launch():
    item = _item()
    analyzed = asyncio.run(
        FoodContentAnalyzer(StubClient([_response()])).analyze_batch([item])
    )[0]

    assert analyzed.food is not None
    assert analyzed.food.category == FoodCategory.PRODUCT_INNOVATION
    assert analyzed.food.importance_score == 8.0
    assert analyzed.food.profile_relevance_score == 8.5
    assert analyzed.food.opportunity_score == 7.0
    assert analyzed.food.evidence_quality_score == 8.0
    assert analyzed.food.event_key == (
        "example|protein-tea|launch|JP|2026-07-24"
    )
    assert analyzed.food.product_launch is not None
    assert analyzed.food.product_launch.product_name == "Protein Tea"
    assert analyzed.metadata["title_zh"] == "Example 在日本推出蛋白茶"
    assert analyzed.ai_summary == (
        "Example 在日本上市一款蛋白茶新品。"
        "产品将高蛋白诉求与即饮茶形态结合。"
        "首发渠道为日本零售市场。"
    )


def test_bad_item_isolated_after_retries_without_failing_batch():
    client = StubClient(["not json", "still not json", _response()])
    bad, good = asyncio.run(
        FoodContentAnalyzer(
            client, max_attempts=2, concurrency=1
        ).analyze_batch([_item("bad"), _item("good")])
    )

    assert bad.ai_score == 0
    assert bad.metadata["foodscope_isolated"] is True
    assert bad.metadata["foodscope_analysis_attempts"] == 2
    assert good.food is not None
    assert good.food.importance_score == 8.0
    assert client.calls == 3


def test_client_error_is_retried_and_isolated():
    client = StubClient(
        [
            RuntimeError("provider unavailable"),
            RuntimeError(
                "still down: https://provider.test/callback"
                "?access_token=supersecret"
            ),
        ]
    )
    item = asyncio.run(
        FoodContentAnalyzer(client, max_attempts=2).analyze_batch([_item()])
    )[0]

    assert client.calls == 2
    assert item.metadata["foodscope_isolated"] is True
    assert item.metadata["foodscope_analysis_error"] == (
        "FoodScope analysis failed (RuntimeError)"
    )
    assert "supersecret" not in json.dumps(item.metadata)


def test_irrelevant_item_is_not_treated_as_an_analysis_failure():
    item = asyncio.run(
        FoodContentAnalyzer(
            StubClient([json.dumps({"relevant": False})])
        ).analyze_batch([_item()])
    )[0]

    assert item.ai_score == 0
    assert item.ai_reason == "Not relevant to the food industry"
    assert item.metadata["foodscope_analysis_attempts"] == 1
    assert "foodscope_isolated" not in item.metadata


def test_malformed_response_is_retried_then_accepted():
    client = StubClient(["not json", _response()])
    item = asyncio.run(
        FoodContentAnalyzer(client, max_attempts=3).analyze_batch([_item()])
    )[0]

    assert client.calls == 2
    assert item.metadata["foodscope_analysis_attempts"] == 2
    assert item.food is not None
    assert item.food.importance_score == 8.0


def test_analysis_preserves_source_evidence_contract():
    item = _item()
    assert item.food is not None
    before = item.food.model_dump(
        include={
            "source_id",
            "source_pack_ids",
            "evidence_tier",
            "collection_tier",
            "original_source_url",
            "evidence_urls",
            "official_evidence_urls",
        }
    )

    analyzed = asyncio.run(
        FoodContentAnalyzer(StubClient([_response()])).analyze_batch([item])
    )[0]

    assert analyzed.food is not None
    after = analyzed.food.model_dump(include=set(before))
    assert after == before


def test_relevant_analysis_without_event_key_uses_canonical_url_fallback():
    response = json.loads(_response())
    response["event_key"] = None
    first = _item("same?utm_source=mail")
    second = _item("same?utm_source=social")

    analyzed = asyncio.run(
        FoodContentAnalyzer(
            StubClient([json.dumps(response), json.dumps(response)])
        ).analyze_batch([first, second])
    )

    assert analyzed[0].food is not None
    assert analyzed[1].food is not None
    assert analyzed[0].food.event_key == analyzed[1].food.event_key
    assert analyzed[0].food.event_key.startswith("url:")
    assert analyzed[0].metadata["foodscope_event_key_source"] == (
        "canonical_url_fallback"
    )
