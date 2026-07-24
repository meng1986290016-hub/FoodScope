"""Independent, idempotent delivery for canonical FoodScope briefs."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any, Sequence

from pydantic import BaseModel

from .briefing import BriefFacts, RenderedBrief
from .config import DeliveryConfig
from .feishu import build_feishu_brief_payload
from .run_store import FoodRunStore


class DeliveryStatus(StrEnum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILURE = "failure"


class DeliveryResult(BaseModel):
    channel: str
    status: DeliveryStatus
    facts_sha256: str
    external_id: str | None = None
    detail: str | None = None


class FoodDeliveryManager:
    """Deliver one immutable fact snapshot without channel coupling."""

    CHANNELS = (
        "archive",
        "email",
        "feishu",
        "wechat_draft",
    )

    def __init__(
        self,
        *,
        run_id: str,
        run_store: FoodRunStore,
        config: DeliveryConfig,
        email_manager: Any = None,
        subscribers: Sequence[str] = (),
        webhook_notifier: Any = None,
        wechat_client: Any = None,
    ) -> None:
        self.run_id = run_id
        self.run_store = run_store
        self.config = config
        self.email_manager = email_manager
        self.subscribers = list(subscribers)
        self.webhook_notifier = webhook_notifier
        self.wechat_client = wechat_client

    async def deliver(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> list[DeliveryResult]:
        """Attempt all channels concurrently and return fixed-order results."""
        if facts.fact_hash() != rendered.facts_sha256:
            raise ValueError(
                "rendered brief does not match canonical facts"
            )

        tasks = [
            self._deliver_channel(channel, facts, rendered)
            for channel in self.CHANNELS
        ]
        raw_results = await asyncio.gather(
            *tasks, return_exceptions=True
        )
        results: list[DeliveryResult] = []
        for channel, raw_result in zip(
            self.CHANNELS, raw_results, strict=True
        ):
            if isinstance(raw_result, BaseException):
                result = self._failure_from_exception(
                    channel, rendered.facts_sha256, raw_result
                )
            else:
                result = raw_result
            self.run_store.record_delivery(
                self.run_id,
                result.channel,
                result.status.value,
                artifact_id=result.facts_sha256,
                external_id=result.external_id,
                detail=result.detail,
            )
            results.append(result)
        return results

    async def _deliver_channel(
        self,
        channel: str,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> DeliveryResult:
        if self.run_store.delivery_succeeded(
            self.run_id, channel, rendered.facts_sha256
        ):
            return DeliveryResult(
                channel=channel,
                status=DeliveryStatus.SKIPPED,
                facts_sha256=rendered.facts_sha256,
                detail="matching fact snapshot already delivered",
            )
        if channel == "archive":
            return self._deliver_archive(rendered)
        if channel == "email":
            return await self._deliver_email(facts, rendered)
        if channel == "feishu":
            return await self._deliver_feishu(facts, rendered)
        if channel == "wechat_draft":
            return await self._deliver_wechat(facts, rendered)
        raise ValueError(f"unknown delivery channel: {channel}")

    def _deliver_archive(
        self, rendered: RenderedBrief
    ) -> DeliveryResult:
        enabled = (
            self.config.markdown_enabled
            or self.config.html_enabled
        )
        if not enabled:
            return self._disabled("archive", rendered)
        manifest = self.run_store.load_manifest(self.run_id)
        if (
            manifest.get("facts_sha256")
            != rendered.facts_sha256
            or not manifest.get("artifacts")
        ):
            return DeliveryResult(
                channel="archive",
                status=DeliveryStatus.FAILURE,
                facts_sha256=rendered.facts_sha256,
                detail="canonical archive is incomplete",
            )
        return DeliveryResult(
            channel="archive",
            status=DeliveryStatus.SUCCESS,
            facts_sha256=rendered.facts_sha256,
            external_id=self.run_id,
        )

    async def _deliver_email(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> DeliveryResult:
        email_config = getattr(
            self.email_manager, "config", None
        )
        if (
            self.email_manager is None
            or not getattr(email_config, "enabled", False)
            or not self.subscribers
        ):
            return self._disabled("email", rendered)
        subject = (
            "FoodScope 全球食品产业简报 · "
            f"{facts.metadata.date}"
        )
        sent = await asyncio.to_thread(
            self.email_manager.send_daily_summary,
            rendered.markdown,
            subject,
            self.subscribers,
            rendered.html,
        )
        if sent is False:
            return DeliveryResult(
                channel="email",
                status=DeliveryStatus.FAILURE,
                facts_sha256=rendered.facts_sha256,
                detail="SMTP delivery failed",
            )
        return DeliveryResult(
            channel="email",
            status=DeliveryStatus.SUCCESS,
            facts_sha256=rendered.facts_sha256,
            external_id=str(len(self.subscribers)),
        )

    async def _deliver_feishu(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> DeliveryResult:
        webhook_config = getattr(
            self.webhook_notifier, "config", None
        )
        platform = str(
            getattr(webhook_config, "platform", "")
        ).lower()
        if (
            self.webhook_notifier is None
            or not getattr(webhook_config, "enabled", False)
            or platform not in {"feishu", "lark"}
        ):
            return self._disabled("feishu", rendered)

        payloads = build_feishu_brief_payload(
            facts, rendered
        )
        delivered = 0
        for payload in payloads:
            response = await self.webhook_notifier.send_payload(
                payload
            )
            if not getattr(response, "sent", False):
                status = getattr(response, "status", "failure")
                status_value = getattr(status, "value", str(status))
                return DeliveryResult(
                    channel="feishu",
                    status=DeliveryStatus.FAILURE,
                    facts_sha256=rendered.facts_sha256,
                    external_id=f"{delivered}/{len(payloads)}",
                    detail=(
                        "Feishu card delivery failed "
                        f"({status_value})"
                    ),
                )
            delivered += 1
        return DeliveryResult(
            channel="feishu",
            status=DeliveryStatus.SUCCESS,
            facts_sha256=rendered.facts_sha256,
            external_id=str(delivered),
        )

    async def _deliver_wechat(
        self,
        facts: BriefFacts,
        rendered: RenderedBrief,
    ) -> DeliveryResult:
        if (
            not self.config.wechat.enabled
            or self.wechat_client is None
        ):
            return self._disabled(
                "wechat_draft", rendered
            )
        result = await self.wechat_client.create_draft(
            facts, rendered
        )
        return DeliveryResult(
            channel="wechat_draft",
            status=result.status,
            facts_sha256=rendered.facts_sha256,
            external_id=result.external_id,
            detail=result.detail,
        )

    @staticmethod
    def _disabled(
        channel: str, rendered: RenderedBrief
    ) -> DeliveryResult:
        return DeliveryResult(
            channel=channel,
            status=DeliveryStatus.DISABLED,
            facts_sha256=rendered.facts_sha256,
        )

    @staticmethod
    def _failure_from_exception(
        channel: str,
        facts_sha256: str,
        error: BaseException,
    ) -> DeliveryResult:
        # Exception text can contain credentials or query strings. Only the
        # class name crosses the delivery boundary.
        return DeliveryResult(
            channel=channel,
            status=DeliveryStatus.FAILURE,
            facts_sha256=facts_sha256,
            detail=(
                f"{channel} delivery failed "
                f"({type(error).__name__})"
            ),
        )

