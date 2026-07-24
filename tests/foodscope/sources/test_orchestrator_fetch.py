import asyncio
from datetime import datetime, timezone

from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.orchestrator import FetchReport, SourceFetchOutcome
from tests.foodscope.test_normalizer import item


def test_foodscope_fetch_keeps_parent_items_and_combines_outcomes(
    monkeypatch,
):
    parent_item = item("parent", "Parent")
    food_item = item("food", "Food")
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {"good": object(), "bad": object()}

    async def parent_fetch(self, since):
        self.last_fetch_report = FetchReport(
            [SourceFetchOutcome("Parent RSS", "success", [parent_item])]
        )
        return [parent_item]

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since):
            return [
                food_item
            ], [
                SourceFetchOutcome("good", "success", [food_item]),
                SourceFetchOutcome(
                    "bad", "failure", error="RuntimeError: broken"
                ),
            ]

    monkeypatch.setattr(
        "src.orchestrator.HorizonOrchestrator.fetch_all_sources",
        parent_fetch,
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.FoodSourceRegistry",
        FakeRegistry,
        raising=False,
    )

    fetched = asyncio.run(
        orchestrator.fetch_all_sources(
            datetime(2026, 7, 24, tzinfo=timezone.utc)
        )
    )

    assert fetched == [parent_item, food_item]
    assert [
        outcome.source_name
        for outcome in orchestrator.last_fetch_report.outcomes
    ] == ["Parent RSS", "good", "bad"]
