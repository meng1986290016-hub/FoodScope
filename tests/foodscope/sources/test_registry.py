import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from src.foodscope.sources.registry import (
    FoodSourceRegistry,
    select_sources_for_run,
)
from src.foodscope.sources.base import BaseFoodAdapter
from src.foodscope.models import CollectionTier
from tests.foodscope.source_factories import rss_source, source


FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "foodscope"
    / "sources"
    / "feed.xml"
).read_bytes()


def test_tier_selection_runs_core_daily_and_rotates_other_tiers():
    core = rss_source("core").model_copy(
        update={"collection_tier": CollectionTier.CORE}
    )
    extended = rss_source("extended").model_copy(
        update={"collection_tier": CollectionTier.EXTENDED}
    )
    discovery = rss_source("discovery").model_copy(
        update={"collection_tier": CollectionTier.DISCOVERY}
    )
    sources = [core, extended, discovery]

    selections = [
        [
            source.id
            for source in select_sources_for_run(
                sources,
                business_date=date(2026, 7, day),
                minimum_sources=1,
                extended_rotation_days=2,
                discovery_rotation_days=3,
            )
        ]
        for day in range(20, 26)
    ]

    assert all("core" in selection for selection in selections)
    assert any(
        "extended" in selection for selection in selections
    )
    assert any(
        "extended" not in selection for selection in selections
    )
    assert any(
        "discovery" in selection for selection in selections
    )
    assert any(
        "discovery" not in selection for selection in selections
    )
    assert selections[0] == [
        source.id
        for source in select_sources_for_run(
            sources,
            business_date=date(2026, 7, 20),
            minimum_sources=1,
            extended_rotation_days=2,
            discovery_rotation_days=3,
        )
    ]


def test_tier_selection_fills_shortage_deterministically():
    sources = [
        rss_source(f"extended-{index}")
        for index in range(4)
    ]

    selected = select_sources_for_run(
        sources,
        business_date=date(2026, 7, 24),
        minimum_sources=4,
        extended_rotation_days=30,
        discovery_rotation_days=30,
    )

    assert [source.id for source in selected] == [
        source.id for source in sources
    ]


def test_registry_fetches_each_source_independently():
    def responses(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(responses)
        ) as client:
            registry = FoodSourceRegistry(http_client=client)
            return await registry.fetch(
                [
                    rss_source(
                        "good",
                        url="https://93.184.216.34/good.xml",
                    ),
                    source(
                        "broken",
                        "does_not_exist",
                        url="https://93.184.216.34/broken",
                    ),
                ],
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    items, outcomes = asyncio.run(run())

    assert len(items) == 1
    assert [outcome.status for outcome in outcomes] == [
        "success",
        "failure",
    ]
    assert outcomes[1].source_name == "broken"
    assert "KeyError" in outcomes[1].error


def test_registry_skips_disabled_sources():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500)
            )
        ) as client:
            return await FoodSourceRegistry(client).fetch(
                [rss_source("disabled", enabled=False)],
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    assert asyncio.run(run()) == ([], [])


def test_registry_propagates_exact_until_to_adapter(monkeypatch):
    observed = []

    class WindowAdapter(BaseFoodAdapter):
        async def fetch(self, source, since, until=None):
            observed.append((since, until))
            return []

    monkeypatch.setitem(
        __import__(
            "src.foodscope.sources.registry",
            fromlist=["ADAPTERS"],
        ).ADAPTERS,
        "rss",
        WindowAdapter,
    )
    since = datetime(2026, 7, 23, tzinfo=timezone.utc)
    until = datetime(2026, 7, 24, tzinfo=timezone.utc)

    async def run():
        async with httpx.AsyncClient() as client:
            return await FoodSourceRegistry(client).fetch(
                [rss_source("windowed")], since, until
            )

    _, outcomes = asyncio.run(run())

    assert observed == [(since, until)]
    assert outcomes[0].window_since == since.isoformat()
    assert outcomes[0].window_until == until.isoformat()


def test_registry_bounds_global_and_per_domain_concurrency(monkeypatch):
    active = 0
    peak = 0
    active_by_domain = {}
    peak_by_domain = {}

    class ConcurrencyAdapter(BaseFoodAdapter):
        async def fetch(self, source, since, until=None):
            nonlocal active, peak
            domain = urlsplit(source.url).hostname
            active += 1
            active_by_domain[domain] = (
                active_by_domain.get(domain, 0) + 1
            )
            peak = max(peak, active)
            peak_by_domain[domain] = max(
                peak_by_domain.get(domain, 0),
                active_by_domain[domain],
            )
            await asyncio.sleep(0.01)
            active -= 1
            active_by_domain[domain] -= 1
            return []

    monkeypatch.setitem(
        __import__(
            "src.foodscope.sources.registry",
            fromlist=["ADAPTERS"],
        ).ADAPTERS,
        "rss",
        ConcurrencyAdapter,
    )
    sources = [
        rss_source("a1", url="https://a.example/1"),
        rss_source("a2", url="https://a.example/2"),
        rss_source("b1", url="https://b.example/1"),
        rss_source("b2", url="https://b.example/2"),
    ]

    async def run():
        async with httpx.AsyncClient() as client:
            return await FoodSourceRegistry(
                client,
                max_concurrency=2,
                per_domain_concurrency=1,
            ).fetch(
                sources,
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    asyncio.run(run())

    assert peak == 2
    assert peak_by_domain == {
        "a.example": 1,
        "b.example": 1,
    }


def test_collection_tier_controls_retry_budget_and_errors_are_safe(
    monkeypatch,
):
    attempts = {}

    class RetryAdapter(BaseFoodAdapter):
        async def fetch(self, source, since, until=None):
            attempts[source.id] = attempts.get(source.id, 0) + 1
            if (
                source.id == "core"
                and attempts[source.id] >= 3
            ):
                return []
            raise RuntimeError(
                "https://provider.test?api_key=source-secret"
            )

    async def no_sleep(delay):
        return None

    monkeypatch.setitem(
        __import__(
            "src.foodscope.sources.registry",
            fromlist=["ADAPTERS"],
        ).ADAPTERS,
        "rss",
        RetryAdapter,
    )
    core = rss_source("core").model_copy(
        update={"collection_tier": CollectionTier.CORE}
    )
    discovery = rss_source("discovery").model_copy(
        update={"collection_tier": CollectionTier.DISCOVERY}
    )

    async def run():
        async with httpx.AsyncClient() as client:
            return await FoodSourceRegistry(
                client,
                sleep=no_sleep,
                jitter=lambda: 0.0,
            ).fetch(
                [core, discovery],
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    _, outcomes = asyncio.run(run())

    assert attempts == {"core": 3, "discovery": 1}
    assert [outcome.status for outcome in outcomes] == [
        "empty",
        "failure",
    ]
    assert outcomes[1].error == (
        "FoodScope source fetch failed (RuntimeError)"
    )
    assert "source-secret" not in str(outcomes)


def test_registry_reports_adapter_date_parse_telemetry(monkeypatch):
    class TelemetryAdapter(BaseFoodAdapter):
        async def fetch(self, source, since, until=None):
            self.raw_candidate_count = 3
            self.date_parse_attempts = 3
            self.date_parse_successes = 2
            return []

    monkeypatch.setitem(
        __import__(
            "src.foodscope.sources.registry",
            fromlist=["ADAPTERS"],
        ).ADAPTERS,
        "rss",
        TelemetryAdapter,
    )

    async def run():
        async with httpx.AsyncClient() as client:
            return await FoodSourceRegistry(client).fetch(
                [rss_source("telemetry")],
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    _, outcomes = asyncio.run(run())

    assert outcomes[0].candidate_count == 0
    assert outcomes[0].published_at_candidate_count == 3
    assert outcomes[0].published_at_parse_count == 2
