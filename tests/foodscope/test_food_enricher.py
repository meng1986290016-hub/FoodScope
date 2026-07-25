import asyncio
import json
from collections import deque
from pathlib import Path

from src.ai.client import AIClient
from src.foodscope.enricher import FoodContentEnricher
from tests.foodscope.test_food_analyzer import _item


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
    return (FIXTURE_DIR / "enrichment_response.json").read_text()


def test_valid_enrichment_populates_six_actionable_fields():
    item = _item()

    enriched = asyncio.run(
        FoodContentEnricher(StubClient([_response()])).enrich([item])
    )[0]

    assert enriched.food is not None
    assert enriched.food.what_happened_zh.startswith(
        "Example 在日本推出"
    )
    assert "跨品类创新" in enriched.food.why_it_matters_zh
    assert "稳定性与口感" in enriched.food.rd_significance_zh
    assert "中国品牌" in enriched.food.opportunity_signal_zh
    assert "目标市场规则" in enriched.food.risk_signal_zh
    assert "小规模配方" in enriched.food.recommended_action_zh


def test_malformed_response_retries_then_succeeds():
    client = StubClient(["not json", _response()])
    item = asyncio.run(
        FoodContentEnricher(client, max_attempts=3).enrich([_item()])
    )[0]

    assert client.calls == 2
    assert item.metadata["foodscope_enrichment_attempts"] == 2
    assert item.food is not None
    assert item.food.what_happened_zh


def test_failed_item_is_isolated_while_other_item_completes():
    client = StubClient(
        ["bad", "still bad", "bad again", _response()]
    )

    failed, completed = asyncio.run(
        FoodContentEnricher(
            client, max_attempts=3, concurrency=1
        ).enrich([_item("failed"), _item("completed")])
    )

    assert failed.metadata["foodscope_isolated"] is True
    assert failed.metadata["foodscope_isolation_stage"] == "enriched"
    assert completed.food is not None
    assert completed.food.recommended_action_zh
    assert client.calls == 4


def test_failed_enrichment_does_not_persist_provider_error_details():
    client = StubClient(
        [
            RuntimeError(
                "https://provider.test?api_key=enrichment-secret"
            )
        ]
    )

    failed = asyncio.run(
        FoodContentEnricher(client, max_attempts=1).enrich([_item()])
    )[0]

    assert failed.metadata["foodscope_analysis_error"] == (
        "FoodScope enrichment failed (RuntimeError)"
    )
    assert "enrichment-secret" not in json.dumps(failed.metadata)
