import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.orchestrator import FetchReport, SourceFetchOutcome
from tests.foodscope.source_factories import rss_source
from tests.foodscope.test_normalizer import item


def test_foodscope_fetch_keeps_parent_items_and_combines_outcomes(
    monkeypatch,
):
    parent_item = item("parent", "Parent")
    food_item = item("food", "Food")
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {"good": object(), "bad": object()}

    async def parent_fetch(self, since, until=None):
        self.last_fetch_report = FetchReport(
            [SourceFetchOutcome("Parent RSS", "success", [parent_item])]
        )
        return [parent_item]

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
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


def test_foodscope_fetch_propagates_exact_window(monkeypatch):
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {"food": object()}
    observed = []

    async def parent_fetch(self, since, until=None):
        observed.append(("parent", since, until))
        self.last_fetch_report = FetchReport([])
        return []

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
            observed.append(("food", since, until))
            return [], []

    monkeypatch.setattr(
        "src.orchestrator.HorizonOrchestrator.fetch_all_sources",
        parent_fetch,
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.FoodSourceRegistry",
        FakeRegistry,
    )
    since = datetime(2026, 7, 23, tzinfo=timezone.utc)
    until = datetime(2026, 7, 24, tzinfo=timezone.utc)

    asyncio.run(orchestrator.fetch_all_sources(since, until))

    assert observed == [
        ("parent", since, until),
        ("food", since, until),
    ]


def test_foodscope_fetch_uses_bounded_deferred_fallback(
    monkeypatch,
):
    first = rss_source("first")
    backup = rss_source("backup")
    backup_item = item("backup-item", "Backup")
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {
        "first": first,
        "backup": backup,
    }
    orchestrator._selected_source_ids = ["first"]
    orchestrator._eligible_source_ids = ["first", "backup"]
    orchestrator.active_run_id = "run-id"
    orchestrator._window_end = datetime(
        2026, 7, 24, tzinfo=timezone.utc
    )
    orchestrator.config = SimpleNamespace(
        collection=SimpleNamespace(
            fallback_sources_per_run=1
        ),
        schedule=SimpleNamespace(timezone="Asia/Shanghai"),
    )
    recorded = []
    orchestrator.run_store = SimpleNamespace(
        set_source_selection=lambda *args, **kwargs: (
            recorded.append((args, kwargs))
        )
    )
    calls = []

    async def parent_fetch(self, since, until=None):
        self.last_fetch_report = FetchReport([])
        return []

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
            source_ids = [source.id for source in sources]
            calls.append(source_ids)
            if source_ids == ["first"]:
                return [], [
                    SourceFetchOutcome(
                        "first",
                        "empty",
                        candidate_count=0,
                    )
                ]
            return [backup_item], [
                SourceFetchOutcome(
                    "backup",
                    "success",
                    items=[backup_item],
                    candidate_count=1,
                )
            ]

    monkeypatch.setattr(
        "src.orchestrator.HorizonOrchestrator.fetch_all_sources",
        parent_fetch,
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.FoodSourceRegistry",
        FakeRegistry,
    )

    fetched = asyncio.run(
        orchestrator.fetch_all_sources(
            datetime(2026, 7, 23, tzinfo=timezone.utc),
            datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
    )

    assert fetched == [backup_item]
    assert calls == [["first"], ["backup"]]
    assert orchestrator._selected_source_ids == [
        "first",
        "backup",
    ]
    assert recorded[0][0][:2] == (
        "run-id",
        ["first", "backup"],
    )
