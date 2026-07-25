import asyncio
import json
from pathlib import Path

import httpx
import pytest

from src.foodscope.briefing import BriefFacts
from src.foodscope.config import WeChatDraftConfig
from src.foodscope.delivery import DeliveryStatus
from src.foodscope.rendering import FoodBriefRenderer
from src.foodscope.wechat import WeChatDraftClient


FIXTURE = Path(
    "tests/fixtures/foodscope/selected_brief_facts.json"
)


def _facts_and_rendered():
    facts = BriefFacts.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )
    return facts, FoodBriefRenderer().render(facts)


def test_enabled_wechat_requires_runtime_credentials_and_thumb(
    monkeypatch,
):
    monkeypatch.delenv("WECHAT_APP_ID", raising=False)
    monkeypatch.delenv("WECHAT_APP_SECRET", raising=False)

    with pytest.raises(
        ValueError, match="WECHAT_APP_ID.*WECHAT_APP_SECRET"
    ):
        WeChatDraftClient(
            WeChatDraftConfig(
                enabled=True,
                thumb_media_id="thumb",
            )
        )

    monkeypatch.setenv("WECHAT_APP_ID", "app")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    with pytest.raises(ValueError, match="thumb_media_id"):
        WeChatDraftClient(
            WeChatDraftConfig(enabled=True)
        )


def test_wechat_creates_one_draft_only(monkeypatch):
    monkeypatch.setenv("WECHAT_APP_ID", "wx-app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "wx-secret")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/cgi-bin/token":
            assert request.method == "GET"
            assert request.url.params["grant_type"] == (
                "client_credential"
            )
            assert request.url.params["appid"] == "wx-app-id"
            assert request.url.params["secret"] == "wx-secret"
            return httpx.Response(
                200,
                json={
                    "access_token": "sensitive-token",
                    "expires_in": 7200,
                },
            )
        assert request.url.path == "/cgi-bin/draft/add"
        assert request.method == "POST"
        assert request.url.params["access_token"] == (
            "sensitive-token"
        )
        payload = json.loads(request.content)
        assert len(payload["articles"]) == 1
        article = payload["articles"][0]
        assert article["author"] == "FoodScope"
        assert article["thumb_media_id"] == "permanent-thumb"
        assert article["content_source_url"] == (
            "https://media.example/protein-tea"
        )
        assert article["need_open_comment"] == 0
        assert article["only_fans_can_comment"] == 0
        assert "事实快照 SHA-256" in article["content"]
        return httpx.Response(
            200, json={"media_id": "draft-media-id"}
        )

    facts, rendered = _facts_and_rendered()
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    client = WeChatDraftClient(
        WeChatDraftConfig(
            enabled=True,
            thumb_media_id="permanent-thumb",
        ),
        client=async_client,
    )
    try:
        result = asyncio.run(
            client.create_draft(facts, rendered)
        )
    finally:
        asyncio.run(async_client.aclose())

    assert result.status == DeliveryStatus.SUCCESS
    assert result.external_id == "draft-media-id"
    assert result.facts_sha256 == facts.fact_hash()
    assert [request.url.path for request in requests] == [
        "/cgi-bin/token",
        "/cgi-bin/draft/add",
    ]


def test_wechat_error_does_not_leak_token_or_query(monkeypatch):
    monkeypatch.setenv("WECHAT_APP_ID", "wx-app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "wx-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(
                200, json={"access_token": "do-not-leak"}
            )
        return httpx.Response(
            200,
            json={
                "errcode": 40001,
                "errmsg": (
                    "invalid token do-not-leak "
                    "?access_token=do-not-leak"
                ),
            },
        )

    facts, rendered = _facts_and_rendered()
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    client = WeChatDraftClient(
        WeChatDraftConfig(
            enabled=True,
            thumb_media_id="permanent-thumb",
        ),
        client=async_client,
    )
    try:
        result = asyncio.run(
            client.create_draft(facts, rendered)
        )
    finally:
        asyncio.run(async_client.aclose())

    assert result.status == DeliveryStatus.FAILURE
    assert "do-not-leak" not in (result.detail or "")
    assert "access_token" not in (result.detail or "")
