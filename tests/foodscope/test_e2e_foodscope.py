from __future__ import annotations

import asyncio
from email.message import Message
import json
from pathlib import Path

import httpx

from src.foodscope.analyzer import FoodContentAnalyzer
from src.foodscope.config import FoodSourceSpec
from src.foodscope.enricher import FoodContentEnricher
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
)
from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.foodscope.wechat import WeChatDraftClient
from src.mcp.service import HorizonPipelineService
from src.models import Config, ContentItem
from src.orchestrator import FetchReport, SourceFetchOutcome
from src.services.webhook import (
    WebhookDeliveryResult,
    WebhookDeliveryStatus,
)
from src.storage.manager import StorageManager


FIXTURES = Path("tests/fixtures/foodscope/e2e")
PROFILES = (
    "balanced",
    "market",
    "new_products",
    "rd",
    "compliance",
)
EXPECTED_FIRST = {
    "market": FoodCategory.CONSUMER_TRENDS,
    "new_products": FoodCategory.PRODUCT_INNOVATION,
    "rd": FoodCategory.INGREDIENTS_TECHNOLOGY,
    "compliance": FoodCategory.REGULATIONS_STANDARDS,
}


class FixtureAIClient:
    def __init__(self, responses, *, default=None):
        self.responses = responses
        self.default = default

    async def complete(self, *, system, user):
        for title, response in self.responses.items():
            if title in user:
                return json.dumps(response, ensure_ascii=False)
        if self.default is not None:
            return json.dumps(self.default, ensure_ascii=False)
        return "not valid JSON"


class FakeSMTP:
    instances = []
    fail = False

    def __init__(self, server, port):
        self.messages: list[Message] = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, username, password):
        return None

    def send_message(self, message):
        self.messages.append(message)
        if self.fail:
            raise RuntimeError("offline SMTP failure")


class FakeFeishu:
    def __init__(self, config):
        self.config = config
        self.payloads = []

    async def send_payload(self, payload):
        self.payloads.append(payload)
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SUCCESS,
            status_code=200,
        )

    async def send_failure(self, date, error_message):
        raise AssertionError("pipeline should not abort")


def _source_specs(feed):
    specs = {}
    for raw in feed:
        source_id = raw["source_id"]
        category = FoodCategory(raw["category"])
        tier = (
            EvidenceTier.PRIMARY
            if category
            in {
                FoodCategory.REGULATIONS_STANDARDS,
                FoodCategory.FOOD_SAFETY_RECALLS,
            }
            else EvidenceTier.INDUSTRY
        )
        specs[source_id] = FoodSourceSpec(
            id=source_id,
            name=f"Fixture {source_id}",
            url="https://sources.foodscope.test/feed",
            adapter="json_api",
            evidence_tier=tier,
            collection_tier=CollectionTier.CORE,
            packs=["e2e"],
            markets=raw["markets"],
            languages=[raw["language"]],
            categories=[category],
        )
    return specs


def _raw_items(feed):
    return [
        ContentItem.model_validate(
            {
                "id": raw["id"],
                "source_type": "food",
                "title": raw["title"],
                "url": raw["url"],
                "content": raw["content"],
                "published_at": raw["published_at"],
                "metadata": {
                    "food_source_id": raw["source_id"],
                    "language": raw["language"],
                },
            }
        )
        for raw in feed
    ]


def _email_html(message):
    return (
        message.get_payload()[1]
        .get_payload(decode=True)
        .decode()
    )


def test_offline_e2e_all_profiles_and_outputs(
    tmp_path, monkeypatch
):
    repo_root = Path(__file__).resolve().parents[2]
    base_config = json.loads(
        (FIXTURES / "config.json").read_text(
            encoding="utf-8"
        )
    )
    analysis = json.loads(
        (FIXTURES / "ai_responses/analysis.json").read_text(
            encoding="utf-8"
        )
    )
    enrichment = json.loads(
        (
            FIXTURES
            / "ai_responses/enrichment.json"
        ).read_text(encoding="utf-8")
    )
    feed_payload = (
        FIXTURES / "feeds/global_items.json"
    ).read_bytes()
    public_requests = []

    def feed_handler(request: httpx.Request):
        public_requests.append(str(request.url))
        assert request.url == (
            httpx.URL(
                "https://fixtures.foodscope.test/global.json"
            )
        )
        return httpx.Response(
            200,
            content=feed_payload,
            headers={"content-type": "application/json"},
        )

    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    monkeypatch.setenv("EMAIL_PASSWORD", "offline")
    monkeypatch.setenv(
        "FOODSCOPE_FEISHU_URL",
        "https://open.feishu.cn/open-apis/bot/v2/hook/offline",
    )
    monkeypatch.setenv("WECHAT_APP_ID", "offline-app")
    monkeypatch.setenv(
        "WECHAT_APP_SECRET", "offline-secret"
    )
    monkeypatch.setattr(
        "src.services.email.smtplib.SMTP_SSL", FakeSMTP
    )
    observed_first = {}
    evidence_decisions = {}

    for profile in PROFILES:
        config_payload = json.loads(
            json.dumps(base_config)
        )
        config_payload["foodscope"]["profile"] = profile
        config_payload["foodscope"]["profile_dir"] = str(
            repo_root / "data/foodscope/profiles"
        )
        config_payload["foodscope"][
            "source_pack_dir"
        ] = str(repo_root / "data/foodscope/source_packs")
        config = Config.model_validate(config_payload)
        storage = StorageManager(
            data_dir=str(tmp_path / profile / "data")
        )
        monkeypatch.setattr(
            storage,
            "load_subscribers",
            lambda: ["reader@example.test"],
        )
        orchestrator = FoodScopeOrchestrator(
            config, storage
        )

        async def fetch_all_sources(since):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    feed_handler
                )
            ) as client:
                response = await client.get(
                    "https://fixtures.foodscope.test/global.json"
                )
                response.raise_for_status()
                feed = response.json()
            items = _raw_items(feed)
            orchestrator.last_fetch_report = FetchReport(
                [
                    SourceFetchOutcome(
                        raw["source_id"],
                        "success",
                        items=[
                            item
                            for item in items
                            if item.metadata[
                                "food_source_id"
                            ]
                            == raw["source_id"]
                        ],
                    )
                    for raw in feed
                ]
                + [
                    SourceFetchOutcome(
                        "offline_failed_source",
                        "failure",
                        error="offline fixture failure",
                    )
                ]
            )
            return items

        feed = json.loads(feed_payload)
        orchestrator.source_specs_by_id = _source_specs(
            feed
        )
        orchestrator.fetch_all_sources = fetch_all_sources
        orchestrator._food_analyzer = FoodContentAnalyzer(
            FixtureAIClient(analysis),
            profile_id=profile,
            max_attempts=1,
        )
        orchestrator._food_enricher = FoodContentEnricher(
            FixtureAIClient(
                {}, default=enrichment
            ),
            max_attempts=1,
        )
        feishu = FakeFeishu(config.webhook)
        orchestrator.webhook_notifier = feishu
        wechat_articles = []

        def wechat_handler(
            request: httpx.Request,
        ) -> httpx.Response:
            if request.url.path == "/cgi-bin/token":
                return httpx.Response(
                    200,
                    json={"access_token": "offline-token"},
                )
            assert request.url.path == "/cgi-bin/draft/add"
            wechat_articles.extend(
                json.loads(request.content)["articles"]
            )
            return httpx.Response(
                200,
                json={
                    "media_id": (
                        f"offline-draft-{profile}"
                    )
                },
            )

        wechat_http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                wechat_handler
            )
        )
        orchestrator.wechat_draft_client = (
            WeChatDraftClient(
                config.delivery.wechat,
                client=wechat_http,
            )
        )
        FakeSMTP.instances = []
        FakeSMTP.fail = profile == "market"
        try:
            asyncio.run(
                orchestrator.run(
                    since="2026-07-23T00:00:00+00:00",
                    until="2026-07-25T00:00:00+00:00",
                )
            )
        finally:
            asyncio.run(wechat_http.aclose())

        manifest = orchestrator.run_store.load_manifest(
            orchestrator.active_run_id
        )
        assert manifest["completed_stages"] == [
            "raw",
            "normalized",
            "scored",
            "filtered",
            "enriched",
            "summary",
        ]
        assert len(manifest["isolation"]) == 1
        assert manifest["deliveries"]["archive"][
            "status"
        ] == "success"
        assert manifest["deliveries"]["feishu"][
            "status"
        ] == "success"
        assert manifest["deliveries"]["wechat_draft"][
            "status"
        ] == "success"
        if profile == "market":
            assert manifest["deliveries"]["email"][
                "status"
            ] == "failure"
        else:
            assert manifest["deliveries"]["email"][
                "status"
            ] == "success"

        facts, rendered = (
            orchestrator.run_store.load_brief_artifacts(
                orchestrator.active_run_id
            )
        )
        selected = [
            item
            for items in facts.sections.values()
            for item in items
        ]
        event_keys = [
            item.food.event_key for item in selected
        ]
        assert len(event_keys) == len(set(event_keys))
        assert any(
            len(item.metadata.get("event_sources", []))
            == 2
            for item in selected
        )
        for item in selected + facts.risk_alerts:
            if item.food.category in {
                FoodCategory.REGULATIONS_STANDARDS,
                FoodCategory.FOOD_SAFETY_RECALLS,
            }:
                assert item.food.official_evidence_urls
        observed_first[profile] = (
            facts.must_read[0].food.category
        )
        evidence_decisions[profile] = {
            item.food.event_key
            for item in selected + facts.risk_alerts
        }
        facts_hash = rendered.facts_sha256
        assert facts_hash in rendered.markdown
        assert facts_hash in rendered.html
        assert all(
            facts_hash in json.dumps(
                payload, ensure_ascii=False
            )
            for payload in feishu.payloads
        )
        assert len(wechat_articles) == 1
        assert facts_hash in wechat_articles[0]["content"]
        if profile != "market":
            assert facts_hash in _email_html(
                FakeSMTP.instances[0].messages[0]
            )
        mcp_payload = HorizonPipelineService(
            foodscope_runs_root=orchestrator.run_store.root
        ).fs_get_latest_brief("facts")
        assert mcp_payload["facts_sha256"] == facts_hash

    for profile, expected in EXPECTED_FIRST.items():
        assert observed_first[profile] == expected
    assert observed_first["balanced"] in {
        FoodCategory.PRODUCT_INNOVATION,
        FoodCategory.INGREDIENTS_TECHNOLOGY,
    }
    assert len(set(observed_first.values())) >= 4
    baseline = evidence_decisions["balanced"]
    assert all(
        decisions == baseline
        for decisions in evidence_decisions.values()
    )
    assert len(public_requests) == len(PROFILES)
