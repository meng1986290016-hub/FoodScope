import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
)
from src.foodscope.sources.x_official_api import XOfficialAPIAdapter
from tests.foodscope.source_factories import source


SINCE = datetime(2026, 7, 24, tzinfo=timezone.utc)


def x_source():
    candidate = source(
        "S021",
        "x_official_api",
        url="https://x.com/FoodNavigator",
        options={
            "username": "FoodNavigator",
            "retention_mode": "metadata_only",
            "evidence_role": "discovery_only",
            "bearer_token_env": "TEST_X_BEARER",
        },
    )
    return candidate.model_copy(
        update={
            "evidence_tier": EvidenceTier.WEAK_SIGNAL,
            "collection_tier": CollectionTier.DISCOVERY,
        }
    )


def test_x_adapter_uses_official_api_and_emits_metadata_only(
    monkeypatch,
):
    monkeypatch.setenv("TEST_X_BEARER", "test-secret-token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == (
            "Bearer test-secret-token"
        )
        if request.url.path.endswith("/by/username/FoodNavigator"):
            return httpx.Response(
                200, json={"data": {"id": "account-1"}}
            )
        if request.url.path.endswith("/account-1/tweets"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "post-1",
                            "text": "A new food product launch signal.",
                            "created_at": "2026-07-24T08:00:00Z",
                        }
                    ]
                },
            )
        raise AssertionError(request.url)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await XOfficialAPIAdapter(client).fetch(
                x_source(), SINCE
            )

    items = asyncio.run(run())

    assert len(requests) == 2
    assert len(items) == 1
    assert items[0].id == "food:S021:post-1"
    assert str(items[0].url) == (
        "https://x.com/FoodNavigator/status/post-1"
    )
    assert items[0].content == "A new food product launch signal."
    assert items[0].metadata["x_account_id"] == "account-1"
    assert items[0].metadata["retention_mode"] == "metadata_only"
    assert "test-secret-token" not in items[0].model_dump_json()


def test_x_adapter_requires_runtime_secret(monkeypatch):
    monkeypatch.delenv("TEST_X_BEARER", raising=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500)
        )
    )
    try:
        with pytest.raises(ValueError, match="TEST_X_BEARER"):
            asyncio.run(
                XOfficialAPIAdapter(client).fetch(x_source(), SINCE)
            )
    finally:
        asyncio.run(client.aclose())
