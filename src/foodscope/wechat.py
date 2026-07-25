"""WeChat Official Account draft creation for FoodScope."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.ai.summarizer import _safe_url

from .briefing import BriefFacts, RenderedBrief
from .config import WeChatDraftConfig
from .delivery import DeliveryResult, DeliveryStatus


TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"


class WeChatDraftClient:
    """Create one draft article; publishing is intentionally unsupported."""

    def __init__(
        self,
        config: WeChatDraftConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.app_id = os.getenv(config.app_id_env)
        self.app_secret = os.getenv(config.app_secret_env)
        self.client = client
        self._validate_runtime()

    def _validate_runtime(self) -> None:
        missing: list[str] = []
        if not self.app_id:
            missing.append(self.config.app_id_env)
        if not self.app_secret:
            missing.append(self.config.app_secret_env)
        if not self.config.thumb_media_id:
            missing.append("delivery.wechat.thumb_media_id")
        if missing:
            raise ValueError(
                "WeChat draft delivery is missing: "
                + ", ".join(missing)
            )

    async def create_draft(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> DeliveryResult:
        if facts.fact_hash() != rendered.facts_sha256:
            raise ValueError(
                "rendered brief does not match canonical facts"
            )
        client = self.client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)
        try:
            token_result = await client.get(
                TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                },
            )
            token_payload = self._json_payload(token_result)
            token = token_payload.get("access_token")
            if (
                token_result.status_code < 200
                or token_result.status_code >= 300
                or not token
            ):
                return self._api_failure(
                    rendered,
                    "token",
                    token_result.status_code,
                    token_payload,
                )

            response = await client.post(
                DRAFT_URL,
                params={"access_token": str(token)},
                json={
                    "articles": [
                        self._article(facts, rendered)
                    ]
                },
            )
            payload = self._json_payload(response)
            if (
                response.status_code < 200
                or response.status_code >= 300
                or payload.get("errcode") not in (None, 0)
                or not payload.get("media_id")
            ):
                return self._api_failure(
                    rendered,
                    "draft",
                    response.status_code,
                    payload,
                )
            return DeliveryResult(
                channel="wechat_draft",
                status=DeliveryStatus.SUCCESS,
                facts_sha256=rendered.facts_sha256,
                external_id=str(payload["media_id"]),
            )
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
        ) as error:
            return DeliveryResult(
                channel="wechat_draft",
                status=DeliveryStatus.FAILURE,
                facts_sha256=rendered.facts_sha256,
                detail=(
                    "WeChat draft request failed "
                    f"({type(error).__name__})"
                ),
            )
        finally:
            if owns_client:
                await client.aclose()

    def _article(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> dict[str, Any]:
        source_url = ""
        if facts.must_read:
            first = facts.must_read[0]
            candidate = (
                first.food.original_source_url
                if first.food is not None
                else str(first.url)
            )
            source_url = _safe_url(candidate) or ""
        digest = (
            f"{facts.metadata.profile_name}：抓取 "
            f"{facts.metadata.fetched_count} 条，"
            f"精选 {facts.metadata.selected_count} 条。"
        )[:120]
        return {
            "title": (
                "食界雷达 · 全球食品产业简报 · "
                f"{facts.metadata.date}"
            )[:64],
            "author": self.config.author[:16],
            "digest": digest,
            "content": rendered.html,
            "content_source_url": source_url,
            "thumb_media_id": self.config.thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }

    @staticmethod
    def _json_payload(
        response: httpx.Response,
    ) -> dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(
                "WeChat API response is not an object"
            )
        return payload

    @staticmethod
    def _api_failure(
        rendered: RenderedBrief,
        operation: str,
        status_code: int,
        payload: dict[str, Any],
    ) -> DeliveryResult:
        error_code = payload.get("errcode", "unknown")
        # Deliberately omit the remote message: it can echo query strings,
        # access tokens, app IDs, or other credential material.
        return DeliveryResult(
            channel="wechat_draft",
            status=DeliveryStatus.FAILURE,
            facts_sha256=rendered.facts_sha256,
            detail=(
                f"WeChat {operation} API failed "
                f"(HTTP {status_code}, code {error_code})"
            ),
        )

