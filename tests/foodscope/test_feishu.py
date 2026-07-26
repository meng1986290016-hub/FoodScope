import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.foodscope.briefing import BriefFacts
from src.foodscope.feishu import build_feishu_brief_payload
from src.foodscope.rendering import FoodBriefRenderer
from tests.foodscope.test_brief_rendering import factual_facts
from src.models import WebhookConfig
from src.services.webhook import (
    WebhookDeliveryStatus,
    WebhookNotifier,
)


FIXTURE = Path(
    "tests/fixtures/foodscope/selected_brief_facts.json"
)


def _facts():
    return BriefFacts.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_feishu_cards_preserve_links_hash_and_collapsed_sections():
    facts = factual_facts()
    rendered = FoodBriefRenderer().render(facts)

    payloads = build_feishu_brief_payload(facts, rendered)

    assert payloads
    first = payloads[0]
    assert first["msg_type"] == "interactive"
    assert first["card"]["schema"] == "2.0"
    serialized = json.dumps(
        first, ensure_ascii=False, separators=(",", ":")
    )
    assert "今日必读" in serialized
    assert "今日新闻" in serialized
    assert "https://official.example/recall" in serialized
    assert rendered.facts_sha256 in serialized

    all_serialized = "\n".join(
        json.dumps(payload, ensure_ascii=False)
        for payload in payloads
    )
    assert "collapsible_panel" in all_serialized
    assert "发生了什么" in all_serialized
    assert "关键事实" in all_serialized
    assert "FoodNavigator" in all_serialized
    assert "2026-07-24 12:00（北京时间）" in all_serialized
    assert "建议动作" not in all_serialized
    assert "https://media.example/protein-tea" in all_serialized
    assert all(
        rendered.facts_sha256
        in json.dumps(payload, ensure_ascii=False)
        for payload in payloads
    )


def test_feishu_cards_split_before_25000_code_points():
    facts = _facts()
    original = facts.sections["product_innovation"][0]
    many = []
    for index in range(80):
        item = original.model_copy(deep=True)
        item.id = f"long-{index}"
        item.metadata["title_zh"] = (
            f"第 {index} 个新品" + "很长的标题" * 30
        )
        many.append(item)
    expanded = facts.model_copy(
        update={
            "risk_alerts": [],
            "must_read": many,
            "news": [],
            "sections": {},
        },
        deep=True,
    )
    rendered = FoodBriefRenderer().render(expanded)

    payloads = build_feishu_brief_payload(expanded, rendered)

    assert len(payloads) > 2
    assert all(
        len(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        < 25_000
        for payload in payloads
    )


def test_webhook_send_payload_posts_exact_json(monkeypatch):
    monkeypatch.setenv(
        "FOODSCOPE_FEISHU_URL",
        "https://open.feishu.cn/open-apis/bot/v2/hook/example",
    )
    notifier = WebhookNotifier(
        WebhookConfig(
            enabled=True,
            url_env="FOODSCOPE_FEISHU_URL",
            platform="feishu",
        )
    )
    response = AsyncMock()
    response.status_code = 200
    response.text = '{"code": 0}'
    response.headers = {}

    with patch(
        "src.services.webhook.safe_request",
        new=AsyncMock(return_value=response),
    ) as request:
        result = asyncio.run(
            notifier.send_payload({"msg_type": "interactive"})
        )

    assert result.status == WebhookDeliveryStatus.SUCCESS
    call = request.await_args
    assert call.args[1:3] == (
        "POST",
        "https://open.feishu.cn/open-apis/bot/v2/hook/example",
    )
    assert json.loads(call.kwargs["content"]) == {
        "msg_type": "interactive"
    }
    assert call.kwargs["headers"]["Content-Type"] == (
        "application/json"
    )
