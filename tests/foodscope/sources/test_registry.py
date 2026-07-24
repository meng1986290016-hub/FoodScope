import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.foodscope.sources.registry import FoodSourceRegistry
from tests.foodscope.source_factories import rss_source, source


FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "foodscope"
    / "sources"
    / "feed.xml"
).read_bytes()


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
