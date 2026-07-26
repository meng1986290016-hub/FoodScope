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


def test_foodscope_fetch_expands_only_empty_direct_source(
    monkeypatch,
):
    busy_source = rss_source("busy")
    empty_source = rss_source("empty")
    busy_item = item("busy-item", "Busy")
    expanded_item = item("expanded-item", "Expanded")
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {
        "busy": busy_source,
        "empty": empty_source,
    }
    orchestrator._selected_source_ids = ["busy", "empty"]
    orchestrator._eligible_source_ids = ["busy", "empty"]
    orchestrator.active_run_id = "run-id"
    initial_since = datetime(
        2026, 7, 24, 18, tzinfo=timezone.utc
    )
    until = datetime(2026, 7, 26, tzinfo=timezone.utc)
    expanded_since = datetime(
        2026, 7, 19, tzinfo=timezone.utc
    )
    middle_since = datetime(
        2026, 7, 23, tzinfo=timezone.utc
    )
    orchestrator._window_start = initial_since
    orchestrator._window_end = until
    orchestrator.config = SimpleNamespace(
        collection=SimpleNamespace(
            fallback_sources_per_run=0,
            adaptive_lookback_enabled=True,
            adaptive_lookback_min_candidates=1,
            adaptive_lookback_hours=[72, 168],
        ),
        schedule=SimpleNamespace(timezone="Asia/Shanghai"),
    )
    orchestrator.run_store = SimpleNamespace(
        set_source_selection=lambda *args, **kwargs: None,
    )
    observed = []

    async def parent_fetch(self, since, until=None):
        self.last_fetch_report = FetchReport([])
        return []

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
            source_ids = [source.id for source in sources]
            observed.append((source_ids, since))
            if since <= expanded_since:
                return [expanded_item], [
                    SourceFetchOutcome(
                        "empty",
                        "success",
                        items=[expanded_item],
                        candidate_count=1,
                        window_since=since.isoformat(),
                        window_until=until.isoformat(),
                    )
                ]
            if source_ids == ["empty"]:
                return [], [
                    SourceFetchOutcome(
                        "empty",
                        "empty",
                        candidate_count=0,
                        window_since=since.isoformat(),
                        window_until=until.isoformat(),
                    )
                ]
            return [busy_item], [
                SourceFetchOutcome(
                    "busy",
                    "success",
                    items=[busy_item],
                    candidate_count=1,
                    window_since=since.isoformat(),
                    window_until=until.isoformat(),
                ),
                SourceFetchOutcome(
                    "empty",
                    "empty",
                    candidate_count=0,
                    window_since=since.isoformat(),
                    window_until=until.isoformat(),
                ),
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
        orchestrator.fetch_all_sources(initial_since, until)
    )

    assert fetched == [busy_item, expanded_item]
    assert observed == [
        (["busy", "empty"], initial_since),
        (["empty"], middle_since),
        (["empty"], expanded_since),
    ]
    assert orchestrator._window_start == initial_since
    outcomes = {
        outcome.source_name: outcome
        for outcome in orchestrator.last_fetch_report.outcomes
    }
    assert outcomes["busy"].window_since == initial_since.isoformat()
    assert outcomes["empty"].window_since == expanded_since.isoformat()


def test_foodscope_fetch_does_not_expand_failed_direct_source(monkeypatch):
    source = rss_source("failed")
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {"failed": source}
    orchestrator._selected_source_ids = ["failed"]
    orchestrator._eligible_source_ids = ["failed"]
    orchestrator.active_run_id = None
    orchestrator.config = SimpleNamespace(
        collection=SimpleNamespace(
            fallback_sources_per_run=0,
            adaptive_lookback_enabled=True,
            adaptive_lookback_min_candidates=1,
            adaptive_lookback_hours=[72, 168],
        ),
        evidence=SimpleNamespace(
            resolve_original_urls=False,
            allow_aggregator_fallback=True,
        ),
    )
    calls = []

    async def parent_fetch(self, since, until=None):
        self.last_fetch_report = FetchReport([])
        return []

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
            calls.append([source.id for source in sources])
            return [], [
                SourceFetchOutcome(
                    "failed",
                    "failure",
                    error="blocked",
                    window_since=since.isoformat(),
                    window_until=until.isoformat(),
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

    asyncio.run(
        orchestrator.fetch_all_sources(
            datetime(2026, 7, 24, 18, tzinfo=timezone.utc),
            datetime(2026, 7, 26, tzinfo=timezone.utc),
        )
    )

    assert calls == [["failed"]]


def test_foodscope_fetch_resolves_discovery_urls_before_returning(
    monkeypatch,
):
    discovered = item("discovered", "Discovered")
    discovered.metadata.update(
        {
            "discovery_provider": "google_news",
            "discovered_source_name": "Publisher",
        }
    )
    orchestrator = object.__new__(FoodScopeOrchestrator)
    orchestrator.source_specs_by_id = {"food": rss_source("food")}
    orchestrator.config = SimpleNamespace(
        collection=SimpleNamespace(
            fallback_sources_per_run=0,
            adaptive_lookback_enabled=False,
            adaptive_lookback_min_candidates=0,
            adaptive_lookback_hours=[],
        ),
        evidence=SimpleNamespace(
            resolve_original_urls=True,
            allow_aggregator_fallback=True,
        ),
    )
    calls = []

    async def parent_fetch(self, since, until=None):
        self.last_fetch_report = FetchReport([])
        return []

    class FakeRegistry:
        def __init__(self, http_client):
            pass

        async def fetch(self, sources, since, until=None):
            return [discovered], [
                SourceFetchOutcome(
                    "food",
                    "success",
                    items=[discovered],
                    candidate_count=1,
                )
            ]

    class FakeResolver:
        def __init__(self, client, *, enabled):
            calls.append(("init", enabled))

        async def resolve_items(
            self, items, *, allow_aggregator_fallback
        ):
            calls.append(
                (
                    "resolve",
                    [entry.id for entry in items],
                    allow_aggregator_fallback,
                )
            )
            items[0].metadata["original_url_resolution_status"] = (
                "fallback"
            )

    monkeypatch.setattr(
        "src.orchestrator.HorizonOrchestrator.fetch_all_sources",
        parent_fetch,
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.FoodSourceRegistry",
        FakeRegistry,
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.OriginalUrlResolver",
        FakeResolver,
        raising=False,
    )

    fetched = asyncio.run(
        orchestrator.fetch_all_sources(
            datetime(2026, 7, 26, tzinfo=timezone.utc)
        )
    )

    assert fetched == [discovered]
    assert calls == [
        ("init", True),
        ("resolve", ["discovered"], True),
    ]
