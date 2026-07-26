import asyncio
from datetime import datetime, timezone

import httpx

from src.foodscope.sources.original_url import OriginalUrlResolver
from src.models import ContentItem, SourceType


async def public_host(_host: str) -> list[str]:
    return ["93.184.216.34"]


def discovery_item(
    item_id: str,
    url: str,
    *,
    publisher: str | None = "Publisher",
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.FOOD,
        title=item_id,
        url=url,
        published_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        metadata={
            "discovery_provider": "google_news",
            "discovered_source_name": publisher,
        },
    )


def test_resolves_public_redirect_to_publisher_domain():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "news.google.com":
            return httpx.Response(
                302,
                headers={
                    "location": "https://publisher.example/story"
                },
            )
        return httpx.Response(200, text="publisher")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            resolver = OriginalUrlResolver(
                client, host_resolver=public_host
            )
            return await resolver.resolve(
                "https://news.google.com/rss/articles/one"
            )

    result = asyncio.run(run())

    assert result.status == "resolved"
    assert result.url == "https://publisher.example/story"
    assert result.publisher_domain == "example"
    assert result.error is None


def test_extracts_public_canonical_url_from_bounded_html():
    html = (
        '<html><head><link rel="canonical" '
        'href="https://publisher.test.com/canonical"></head></html>'
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        ) as client:
            resolver = OriginalUrlResolver(
                client, host_resolver=public_host
            )
            return await resolver.resolve(
                "https://news.google.com/rss/articles/two"
            )

    result = asyncio.run(run())

    assert result.status == "resolved"
    assert result.url == "https://publisher.test.com/canonical"
    assert result.publisher_domain == "test.com"


def test_rejects_private_literal_without_sending_request():
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await OriginalUrlResolver(client).resolve(
                "http://127.0.0.1/private"
            )

    result = asyncio.run(run())

    assert result.status == "failed"
    assert result.error == "unsafe_target"
    assert requests == 0


def test_reuses_resolution_for_duplicate_url():
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if request.url.host == "publisher.example":
            return httpx.Response(200)
        return httpx.Response(
            302,
            headers={
                "location": "https://publisher.example/story"
            },
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            resolver = OriginalUrlResolver(
                client, host_resolver=public_host
            )
            url = "https://news.google.com/rss/articles/repeated"
            return await asyncio.gather(
                resolver.resolve(url),
                resolver.resolve(url),
            )

    first, second = asyncio.run(run())

    assert first == second
    assert requests == 1


def test_disabled_resolver_does_not_send_request():
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await OriginalUrlResolver(
                client, enabled=False
            ).resolve("https://news.google.com/rss/articles/off")

    result = asyncio.run(run())

    assert result.status == "disabled"
    assert requests == 0


def test_resolve_items_records_resolved_and_fallback_statuses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/resolved"):
            return httpx.Response(
                302,
                headers={
                    "location": "https://publisher.example/story"
                },
            )
        if request.url.host == "publisher.example":
            return httpx.Response(200)
        return httpx.Response(503)

    resolved = discovery_item(
        "resolved",
        "https://news.google.com/rss/articles/resolved",
    )
    fallback = discovery_item(
        "fallback",
        "https://news.google.com/rss/articles/fallback",
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            resolver = OriginalUrlResolver(
                client, host_resolver=public_host
            )
            await resolver.resolve_items(
                [resolved, fallback],
                allow_aggregator_fallback=True,
            )

    asyncio.run(run())

    assert resolved.metadata["original_url_resolution_status"] == (
        "resolved"
    )
    assert resolved.metadata["resolved_original_url"] == (
        "https://publisher.example/story"
    )
    assert resolved.metadata["publisher_domain"] == "example"
    assert fallback.metadata["original_url_resolution_status"] == (
        "fallback"
    )
    assert "resolved_original_url" not in fallback.metadata


def test_dns_resolution_is_bounded_by_timeout():
    async def hanging_host(_host: str) -> list[str]:
        await asyncio.Event().wait()
        return []

    html = (
        '<link rel="canonical" '
        'href="https://publisher.example/story">'
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        ) as client:
            resolver = OriginalUrlResolver(
                client,
                timeout_seconds=0.01,
                host_resolver=hanging_host,
            )
            return await asyncio.wait_for(
                resolver.resolve(
                    "https://news.google.com/rss/articles/dns"
                ),
                timeout=0.2,
            )

    result = asyncio.run(run())

    assert result.status == "failed"
    assert result.error == "unsafe_target"


def test_resolver_never_requests_untrusted_initial_host():
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            resolver = OriginalUrlResolver(
                client, host_resolver=public_host
            )
            return await resolver.resolve(
                "https://publisher.example/direct"
            )

    result = asyncio.run(run())

    assert result.status == "failed"
    assert result.error == "unsupported_aggregator"
    assert requests == 0
