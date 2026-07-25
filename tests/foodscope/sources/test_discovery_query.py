import asyncio
from datetime import datetime, timezone

import httpx

from src.foodscope.sources.discovery_query import (
    DiscoveryQueryAdapter,
)
from src.models import SourceType
from tests.foodscope.source_factories import source


GOOGLE_FEED = """\
<rss version="2.0"><channel><item>
<guid>google-one</guid>
<title>Google food launch - Publisher</title>
<link>https://news.google.com/articles/one</link>
<pubDate>Fri, 24 Jul 2026 08:00:00 GMT</pubDate>
<source>Publisher</source>
</item></channel></rss>
"""


def test_discovery_query_dispatches_enabled_providers_as_food_items():
    query_source = source(
        "en_product_launch",
        "discovery_query",
        options={
            "providers": ["google_news", "gdelt"],
            "query": '(food OR beverage) "new product"',
            "category_hint": ["product_innovation"],
            "max_candidates_per_provider": 20,
            "max_candidates_after_dedup": 12,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "news.google.com":
            return httpx.Response(200, text=GOOGLE_FEED)
        if request.url.host == "api.gdeltproject.org":
            return httpx.Response(
                200,
                json={
                    "articles": [
                        {
                            "url": "https://publisher.example/gdelt",
                            "title": "GDELT ingredient investment",
                            "seendate": "20260724T090000Z",
                            "domain": "publisher.example",
                            "language": "English",
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected host {request.url.host}")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await DiscoveryQueryAdapter(client).fetch(
                query_source,
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

    items = asyncio.run(run())

    assert len(items) == 2
    assert all(item.source_type == SourceType.FOOD for item in items)
    assert {item.metadata["discovery_provider"] for item in items} == {
        "google_news",
        "gdelt",
    }
    assert all(
        item.metadata["food_source_id"] == "en_product_launch"
        for item in items
    )
    gdelt = next(
        item
        for item in items
        if item.metadata["discovery_provider"] == "gdelt"
    )
    assert gdelt.metadata["resolved_original_url"] == str(gdelt.url)
