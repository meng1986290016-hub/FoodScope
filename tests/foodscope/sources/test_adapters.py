import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.foodscope.sources.documents import DocumentIndexAdapter
from src.foodscope.sources.html_list import HTMLListAdapter
from src.foodscope.sources.json_api import JSONAPIAdapter
from src.foodscope.sources.rss import RSSFoodAdapter
from src.models import SourceType
from src.url_security import UnsafeURLError
from tests.foodscope.source_factories import rss_source, source


FIXTURES = Path(__file__).parents[2] / "fixtures" / "foodscope" / "sources"
SINCE = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _client(path: str, content: bytes, content_type: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": content_type},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_rss_honors_window_and_emits_food_source_contract():
    async def run():
        async with _client(
            "/feed.xml",
            (FIXTURES / "feed.xml").read_bytes(),
            "application/rss+xml",
        ) as client:
            return await RSSFoodAdapter(client).fetch(
                rss_source(
                    "rss_fixture",
                    url="https://93.184.216.34/feed.xml",
                ),
                SINCE,
            )

    items = asyncio.run(run())

    assert len(items) == 1
    assert items[0].source_type == SourceType.FOOD
    assert items[0].id.startswith("food:rss_fixture:")
    assert items[0].title == "New cultured drink launches"
    assert str(items[0].url).endswith("/articles/new-product")
    assert items[0].content == "A concise launch description."
    assert items[0].published_at.tzinfo == timezone.utc
    assert items[0].metadata["food_source_id"] == "rss_fixture"


def test_json_api_uses_configured_paths_and_fields():
    api_source = source(
        "api_fixture",
        "json_api",
        url="https://93.184.216.34/api.json",
        options={
            "items_path": "result.articles",
            "title_field": "headline",
            "url_field": "href",
            "date_field": "published",
            "content_field": "dek",
        },
    )

    async def run():
        async with _client(
            "/api.json",
            (FIXTURES / "api.json").read_bytes(),
            "application/json",
        ) as client:
            return await JSONAPIAdapter(client).fetch(api_source, SINCE)

    items = asyncio.run(run())

    assert [item.title for item in items] == ["Protein snack launch"]
    assert items[0].content == "A bounded API description."


def test_html_list_uses_configured_selectors():
    html_source = source(
        "html_fixture",
        "html_list",
        url="https://93.184.216.34/list.html",
        options={
            "item_selector": "article.news",
            "title_selector": "h2",
            "link_selector": "h2 a",
            "date_selector": "time",
            "content_selector": ".dek",
        },
    )

    async def run():
        async with _client(
            "/list.html",
            (FIXTURES / "list.html").read_bytes(),
            "text/html",
        ) as client:
            return await HTMLListAdapter(client).fetch(
                html_source, SINCE
            )

    items = asyncio.run(run())

    assert [item.title for item in items] == ["Fresh launch"]
    assert str(items[0].url) == (
        "https://93.184.216.34/articles/fresh-launch"
    )
    assert items[0].content == "A permitted short listing description."


def test_document_index_emits_metadata_without_full_document_body():
    document_source = source(
        "document_fixture",
        "document_index",
        url="https://93.184.216.34/list.html",
        options={
            "item_selector": "li.document",
            "title_selector": ".document-link",
            "link_selector": ".document-link",
            "date_selector": "time",
        },
    )

    async def run():
        async with _client(
            "/list.html",
            (FIXTURES / "list.html").read_bytes(),
            "text/html",
        ) as client:
            return await DocumentIndexAdapter(client).fetch(
                document_source, SINCE
            )

    items = asyncio.run(run())

    assert len(items) == 1
    assert str(items[0].url).endswith("/documents/standard.pdf")
    assert items[0].content is None
    assert items[0].metadata["media_type"] == "application/pdf"


def test_adapter_rejects_private_network_source_url():
    private_source = rss_source(
        "private", url="http://127.0.0.1/feed.xml"
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="")
        )
    )
    try:
        with pytest.raises(UnsafeURLError):
            asyncio.run(RSSFoodAdapter(client).fetch(private_source, SINCE))
    finally:
        asyncio.run(client.aclose())
