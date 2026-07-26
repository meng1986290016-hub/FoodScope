import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.foodscope.sources.html_list import HTMLListAdapter
from tests.foodscope.source_factories import source


FIXTURES = Path(__file__).parents[2] / "fixtures" / "foodscope" / "sources"
SINCE = datetime(2026, 7, 23, tzinfo=timezone.utc)
UNTIL = datetime(2026, 7, 25, tzinfo=timezone.utc)


def test_william_reed_listing_reads_detail_body_and_filters_paid_items():
    spec = source(
        "M001",
        "html_list",
        url="https://93.184.216.34/",
        options={
            "item_selector": "article.card",
            "title_selector": ".card-text-headline a",
            "link_selector": ".card-text-headline a",
            "date_selector": "time",
            "url_include_pattern": r"/Article/",
            "exclude_text_pattern": r"(?i)Paid for by",
            "detail_content_selector": ".article-body",
            "max_detail_content_fetches": 10,
            "require_content": True,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=(FIXTURES / "william_reed_list.html").read_bytes(),
            )
        if request.url.path == "/Article/2026/07/24/protein-launch/":
            return httpx.Response(
                200,
                content=(FIXTURES / "william_reed_detail.html").read_bytes(),
            )
        raise AssertionError(f"unexpected request {request.url}")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await HTMLListAdapter(client).fetch(
                spec, SINCE, UNTIL
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == [
        "Protein launch expands in Europe"
    ]
    assert str(items[0].url).endswith(
        "/Article/2026/07/24/protein-launch/"
    )
    assert items[0].published_at == datetime(
        2026, 7, 24, 13, 51, 57, tzinfo=timezone.utc
    )
    assert items[0].content == (
        "The company launched a high-protein snack in France and Germany. "
        "The product will enter grocery stores in September."
    )


def test_fdt_listing_parses_posted_date_and_keeps_news_only():
    spec = source(
        "M017",
        "html_list",
        url="https://93.184.216.34/",
        options={
            "item_selector": "article",
            "title_selector": ".articleExcerpt h3 a",
            "link_selector": ".articleExcerpt h3 a",
            "date_selector": ".meta",
            "date_text_pattern": r"posted\s+(.+)",
            "detail_date_jsonld_field": "datePublished",
            "max_detail_date_fetches": 10,
            "prefer_detail_date": True,
            "url_include_pattern": r"/news/",
            "detail_content_selector": ".entry-content",
            "max_detail_content_fetches": 10,
            "require_content": True,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=(FIXTURES / "fdt_list.html").read_bytes(),
            )
        if request.url.path.startswith("/news/"):
            return httpx.Response(
                200,
                content=(FIXTURES / "fdt_detail.html").read_bytes(),
            )
        raise AssertionError(f"unexpected request {request.url}")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await HTMLListAdapter(client).fetch(
                spec, SINCE, UNTIL
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == [
        "Process complexity holding back innovation"
    ]
    assert items[0].published_at == datetime(
        2026, 7, 24, 8, 30, tzinfo=timezone.utc
    )
    assert items[0].content == (
        "Manufacturers report that disconnected data slows product "
        "development. The research covered regulatory and formulation teams."
    )
