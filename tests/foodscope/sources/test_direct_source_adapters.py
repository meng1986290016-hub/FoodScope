import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from src.foodscope.config import SourcePackManifest
from src.foodscope.sources.html_list import HTMLListAdapter
from src.foodscope.sources.registry import ADAPTERS
from tests.foodscope.source_factories import source


FIXTURES = Path(__file__).parents[2] / "fixtures" / "foodscope" / "sources"
SINCE = datetime(2026, 7, 23, tzinfo=timezone.utc)
UNTIL = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _configured_source(source_id: str):
    payload = json.loads(
        Path("data/foodscope/source_packs/global_industry.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = SourcePackManifest.model_validate(payload)
    return next(
        item for item in manifest.sources if item.id == source_id
    )


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


def test_fooddive_config_reads_official_feed_with_published_date():
    spec = _configured_source("M004").model_copy(
        update={
            "url": "https://93.184.216.34/feeds/news/"
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(FIXTURES / "fooddive_feed.xml").read_bytes(),
            headers={"content-type": "application/rss+xml"},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await ADAPTERS[spec.adapter](client).fetch(
                spec, SINCE, UNTIL
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == [
        "Nestlé to sell half of waters business in $3.4B deal"
    ]
    assert str(items[0].url) == (
        "https://www.fooddive.com/news/"
        "nestle-sells-half-water-premium-beverage-business-Peranel/826150/"
    )
    assert items[0].published_at == datetime(
        2026, 7, 24, 15, 18, tzinfo=timezone.utc
    )
    assert items[0].content == (
        "The transaction creates an independent premium waters company."
    )


def test_foodbev_config_reads_official_feed_with_published_date():
    spec = _configured_source("M003").model_copy(
        update={
            "url": "https://93.184.216.34/blog-feed.xml"
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(FIXTURES / "foodbev_feed.xml").read_bytes(),
            headers={"content-type": "application/rss+xml"},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await ADAPTERS[spec.adapter](client).fetch(
                spec, SINCE, UNTIL
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == [
        "Oato jumps on matcha trend with limited-edition Oat Matcha Latte"
    ]
    assert str(items[0].url) == (
        "https://www.foodbev.com/post301/"
        "oato-jumps-on-matcha-trend-with-limited-edition-oat-matcha-latte"
    )
    assert items[0].published_at == datetime(
        2026, 7, 24, 12, 0, 20, tzinfo=timezone.utc
    )
    assert items[0].content == (
        "Oato has added an Oat Matcha Latte to its portfolio."
    )


def _foodmanufacture_items():
    spec = _configured_source("M007").model_copy(
        update={"url": "https://93.184.216.34/"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=(
                    FIXTURES / "foodmanufacture_list.html"
                ).read_bytes(),
            )
        if request.url.path == "/Article/2026/07/24/dairy-recall/":
            return httpx.Response(
                200,
                content=(
                    FIXTURES / "foodmanufacture_detail.html"
                ).read_bytes(),
            )
        raise AssertionError(f"unexpected request {request.url}")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await ADAPTERS[spec.adapter](client).fetch(
                spec, SINCE, UNTIL
            )

    return asyncio.run(run())


def test_foodmanufacture_config_reads_jsonld_article_body():
    items = _foodmanufacture_items()

    assert items[0].content == (
        "Graham's Family Dairy is recalling its semi-skimmed milk because "
        "veterinary medicines, including antibiotics, were found in the "
        "product."
    )


def test_html_listing_emits_repeated_article_url_once():
    items = _foodmanufacture_items()

    assert len(items) == 1


def test_jsonld_date_prefers_precise_article_timestamp():
    items = _foodmanufacture_items()

    assert items[0].published_at == datetime(
        2026, 7, 24, 9, 11, 55, tzinfo=timezone.utc
    )


def test_ift_config_reads_current_magazine_listing_and_detail_body():
    spec = _configured_source("M012").model_copy(
        update={"url": "https://93.184.216.34/"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=(FIXTURES / "ift_list.html").read_bytes(),
            )
        if request.url.path.startswith("/food-technology-magazine/"):
            return httpx.Response(
                200,
                content=(FIXTURES / "ift_detail.html").read_bytes(),
            )
        raise AssertionError(f"unexpected request {request.url}")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await ADAPTERS[spec.adapter](client).fetch(
                spec, SINCE, UNTIL
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == [
        "Ashwagandha Gains Traction as Interest in Adaptogens Grows"
    ]
    assert items[0].published_at == datetime(
        2026, 7, 23, 10, 45, tzinfo=timezone.utc
    )
    assert items[0].content == (
        "Consumers are showing growing interest in adaptogens, the natural, "
        "nontoxic plants traditionally used to help the body adapt to stress. "
        "Ashwagandha has emerged as an ingredient for functional foods and "
        "beverages."
    )
