import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.foodscope.briefing import BriefFacts
from src.foodscope.config import DeliveryConfig
from src.foodscope.delivery import (
    DeliveryResult,
    DeliveryStatus,
    FoodDeliveryManager,
)
from src.foodscope.rendering import FoodBriefRenderer
from src.foodscope.run_store import FoodRunStore
from src.services.webhook import (
    WebhookDeliveryResult,
    WebhookDeliveryStatus,
)


FIXTURE = Path(
    "tests/fixtures/foodscope/selected_brief_facts.json"
)


class FailingEmail:
    config = SimpleNamespace(enabled=True)

    def __init__(self):
        self.calls = 0

    def send_daily_summary(
        self, summary_md, subject, subscribers, html_body=None
    ):
        self.calls += 1
        raise RuntimeError("smtp password=do-not-record")


class SuccessfulFeishu:
    config = SimpleNamespace(enabled=True, platform="feishu")

    def __init__(self):
        self.calls = 0

    async def send_payload(self, payload):
        self.calls += 1
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SUCCESS,
            status_code=200,
        )


class SuccessfulWeChat:
    def __init__(self):
        self.calls = 0

    async def create_draft(self, facts, rendered):
        self.calls += 1
        return DeliveryResult(
            channel="wechat_draft",
            status=DeliveryStatus.SUCCESS,
            facts_sha256=rendered.facts_sha256,
            external_id="draft-media-id",
        )


class PartialEmail:
    config = SimpleNamespace(enabled=True)

    def __init__(self):
        self.calls = []
        self.fail_second = True

    def send_daily_summary(
        self, summary_md, subject, subscribers, html_body=None
    ):
        self.calls.append(subscribers[0])
        if subscribers[0] == "second@example.com" and self.fail_second:
            raise RuntimeError("smtp token=partial-secret")
        return True


class PartialFeishu:
    config = SimpleNamespace(enabled=True, platform="feishu")

    def __init__(self):
        self.calls = []
        self.fail_second = True

    async def send_payload(self, payload):
        self.calls.append(payload["card"])
        if payload["card"] == 2 and self.fail_second:
            return WebhookDeliveryResult(
                WebhookDeliveryStatus.HTTP_FAILURE,
                status_code=500,
            )
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SUCCESS,
            status_code=200,
        )


class PartialGenericWebhook:
    def __init__(self):
        self.calls = []
        self.fail_second = True

    async def notify(self, message):
        self.calls.append(message["message"])
        if message["message"] == 2 and self.fail_second:
            return WebhookDeliveryResult(
                WebhookDeliveryStatus.HTTP_FAILURE,
                status_code=500,
            )
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SUCCESS,
            status_code=200,
        )


def _facts_and_rendered():
    facts = BriefFacts.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )
    return facts, FoodBriefRenderer().render(facts)


def _manager(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app-secret")
    run_store = FoodRunStore(tmp_path / "runs")
    run_id = run_store.create_run("balanced")
    facts, rendered = _facts_and_rendered()
    run_store.save_brief_artifacts(run_id, facts, rendered)
    email = FailingEmail()
    feishu = SuccessfulFeishu()
    wechat = SuccessfulWeChat()
    manager = FoodDeliveryManager(
        run_id=run_id,
        run_store=run_store,
        config=DeliveryConfig.model_validate(
            {
                "wechat": {
                    "enabled": True,
                    "thumb_media_id": "permanent-thumb",
                }
            }
        ),
        email_manager=email,
        subscribers=["reader@example.com"],
        webhook_notifier=feishu,
        wechat_client=wechat,
    )
    return (
        manager,
        run_store,
        run_id,
        facts,
        rendered,
        email,
        feishu,
        wechat,
    )


def test_one_failed_channel_does_not_block_others(
    tmp_path, monkeypatch
):
    (
        manager,
        run_store,
        run_id,
        facts,
        rendered,
        _,
        _,
        _,
    ) = _manager(tmp_path, monkeypatch)

    results = asyncio.run(manager.deliver(facts, rendered))

    assert {
        result.channel: result.status.value for result in results
    } == {
        "archive": "success",
        "email": "failure",
        "feishu": "success",
        "wechat_draft": "success",
    }
    assert [result.channel for result in results] == [
        "archive",
        "email",
        "feishu",
        "wechat_draft",
    ]
    assert {
        result.facts_sha256 for result in results
    } == {facts.fact_hash()}
    assert "password" not in (results[1].detail or "")
    assert run_store.load_manifest(run_id)["deliveries"][
        "wechat_draft"
    ]["artifact_id"] == facts.fact_hash()


def test_successful_delivery_is_idempotent(tmp_path, monkeypatch):
    (
        manager,
        run_store,
        run_id,
        facts,
        rendered,
        email,
        feishu,
        wechat,
    ) = _manager(tmp_path, monkeypatch)

    first = asyncio.run(manager.deliver(facts, rendered))
    feishu_calls_after_first = feishu.calls
    second = asyncio.run(manager.deliver(facts, rendered))

    first_by_channel = {result.channel: result for result in first}
    second_by_channel = {result.channel: result for result in second}
    assert first_by_channel["wechat_draft"].status == "success"
    assert second_by_channel["wechat_draft"].status == "skipped"
    assert feishu_calls_after_first > 0
    assert feishu.calls == feishu_calls_after_first
    assert wechat.calls == 1
    assert email.calls == 2
    deliveries = run_store.load_manifest(run_id)["deliveries"]
    assert deliveries["archive"]["attempts"] == 1
    assert deliveries["feishu"]["attempts"] == 1
    assert deliveries["wechat_draft"]["attempts"] == 1
    assert deliveries["email"]["attempts"] == 2


def test_partial_email_retry_skips_recipient_already_delivered(
    tmp_path,
):
    run_store = FoodRunStore(tmp_path / "runs")
    run_id = run_store.create_run("balanced")
    facts, rendered = _facts_and_rendered()
    run_store.save_brief_artifacts(run_id, facts, rendered)
    email = PartialEmail()
    manager = FoodDeliveryManager(
        run_id=run_id,
        run_store=run_store,
        config=DeliveryConfig(),
        email_manager=email,
        subscribers=[
            "first@example.com",
            "second@example.com",
        ],
    )

    first = asyncio.run(manager.deliver(facts, rendered))
    email.fail_second = False
    second = asyncio.run(manager.deliver(facts, rendered))

    assert {result.channel: result.status for result in first}[
        "email"
    ] == DeliveryStatus.FAILURE
    assert {result.channel: result.status for result in second}[
        "email"
    ] == DeliveryStatus.SUCCESS
    assert email.calls == [
        "first@example.com",
        "second@example.com",
        "second@example.com",
    ]
    manifest_text = str(run_store.load_manifest(run_id))
    assert "first@example.com" not in manifest_text
    assert "second@example.com" not in manifest_text
    assert "partial-secret" not in manifest_text


def test_partial_feishu_retry_skips_card_already_delivered(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "src.foodscope.delivery.build_feishu_brief_payload",
        lambda facts, rendered: [{"card": 1}, {"card": 2}],
    )
    run_store = FoodRunStore(tmp_path / "runs")
    run_id = run_store.create_run("balanced")
    facts, rendered = _facts_and_rendered()
    run_store.save_brief_artifacts(run_id, facts, rendered)
    feishu = PartialFeishu()
    manager = FoodDeliveryManager(
        run_id=run_id,
        run_store=run_store,
        config=DeliveryConfig(),
        webhook_notifier=feishu,
    )

    first = asyncio.run(manager.deliver(facts, rendered))
    feishu.fail_second = False
    second = asyncio.run(manager.deliver(facts, rendered))

    assert {result.channel: result.status for result in first}[
        "feishu"
    ] == DeliveryStatus.FAILURE
    assert {result.channel: result.status for result in second}[
        "feishu"
    ] == DeliveryStatus.SUCCESS
    assert feishu.calls == [1, 2, 2]


def test_generic_webhook_messages_are_individually_idempotent(
    tmp_path,
):
    run_store = FoodRunStore(tmp_path / "runs")
    run_id = run_store.create_run("balanced")
    facts, rendered = _facts_and_rendered()
    notifier = PartialGenericWebhook()
    manager = FoodDeliveryManager(
        run_id=run_id,
        run_store=run_store,
        config=DeliveryConfig(),
        webhook_notifier=notifier,
    )
    messages = [
        {"message": 1, "timestamp": "100"},
        {"message": 2, "timestamp": "100"},
    ]

    first = asyncio.run(
        manager.deliver_generic_webhook(
            [
                {"message": 1, "timestamp": "200"},
                {"message": 2, "timestamp": "200"},
            ],
            rendered.facts_sha256,
        )
    )
    notifier.fail_second = False
    second = asyncio.run(
        manager.deliver_generic_webhook(
            messages, rendered.facts_sha256
        )
    )

    assert first.status == DeliveryStatus.FAILURE
    assert second.status == DeliveryStatus.SUCCESS
    assert notifier.calls == [1, 2, 2]
    assert run_store.delivery_succeeded(
        run_id, "webhook", rendered.facts_sha256
    )
