import asyncio
import json
from datetime import datetime
from pathlib import Path

from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    RiskLevel,
)
from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.models import Config, ContentItem
from src.orchestrator import FetchReport, SourceFetchOutcome
from src.storage.manager import StorageManager
from tests.foodscope.test_config_models import legacy_config
from tests.foodscope.test_normalizer import item


class FakeAnalyzer:
    async def analyze_batch(self, items):
        for candidate in items:
            assert candidate.food is not None
            if candidate.id == "bad":
                candidate.ai_score = 0
                candidate.metadata.update(
                    {
                        "foodscope_isolated": True,
                        "foodscope_analysis_error": "invalid JSON",
                    }
                )
                continue
            candidate.ai_score = 8
            candidate.food.importance_score = 8
            candidate.food.profile_relevance_score = 8
            candidate.food.opportunity_score = 8
            candidate.food.evidence_quality_score = 8
            candidate.food.risk_level = RiskLevel.NONE
            candidate.food.event_key = (
                "example|protein-tea|launch|JP|2026-07-24"
            )
        return items


class FakeEnricher:
    async def enrich(self, items):
        for candidate in items:
            assert candidate.food is not None
            candidate.food.what_happened_zh = "有效资讯进入简报。"
        return items


def _config() -> Config:
    raw = legacy_config()
    raw["ai"]["languages"] = ["zh"]
    raw["foodscope"] = {
        "enabled": True,
        "source_packs": [],
    }
    raw["ai_routes"] = {
        "fast": raw["ai"],
        "analysis": raw["ai"],
    }
    return Config.model_validate(raw)


def test_foodscope_run_persists_all_stages_and_isolates_bad_item(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    orchestrator.source_specs_by_id = {
        "M001": FoodSourceSpec(
            id="M001",
            name="Industry source",
            url="https://example.com",
            adapter="rss",
            evidence_tier=EvidenceTier.INDUSTRY,
            collection_tier=CollectionTier.CORE,
            packs=["global_industry"],
            markets=["JP"],
            languages=["en"],
            categories=[FoodCategory.PRODUCT_INNOVATION],
        )
    }
    orchestrator._food_analyzer = FakeAnalyzer()
    orchestrator._food_enricher = FakeEnricher()
    raw_items = [item("bad", "Bad"), item("good", "Good")]
    for candidate in raw_items:
        candidate.metadata["food_source_id"] = "M001"

    async def fetch_all_sources(since):
        orchestrator.last_fetch_report = FetchReport(
            [
                SourceFetchOutcome(
                    "M001", "success", items=raw_items
                )
            ]
        )
        return raw_items

    monkeypatch.setattr(
        orchestrator, "fetch_all_sources", fetch_all_sources
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

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
    assert manifest["isolation"][0]["item_id"] == "bad"
    summary = orchestrator.run_store.load_stage(
        orchestrator.active_run_id, "summary"
    )
    assert "Good" in summary["markdown"]
    assert "Bad" not in summary["markdown"]
    assert len(manifest["source_metrics"]) == 1
    metric = manifest["source_metrics"][0]
    assert metric["source_id"] == "M001"
    assert metric["candidate_count"] == 2
    assert metric["food_relevant_count"] == 1
    assert metric["admitted_count"] == 1
    run_dir = storage.data_dir / "runs" / orchestrator.active_run_id
    assert (run_dir / "facts.json").is_file()
    assert (run_dir / "brief.md").is_file()
    assert (run_dir / "brief.html").is_file()
    facts = json.loads(
        (run_dir / "facts.json").read_text(encoding="utf-8")
    )
    assert facts["metadata"]["profile_id"] == "balanced"
    facts_hash = manifest["facts_sha256"]
    assert facts_hash in summary["markdown"]
    assert facts_hash in (run_dir / "brief.html").read_text(
        encoding="utf-8"
    )
    assert {
        channel: result["status"]
        for channel, result in manifest["deliveries"].items()
    } == {
        "archive": "success",
        "email": "disabled",
        "feishu": "disabled",
        "wechat_draft": "disabled",
    }


def test_explicit_window_filters_items_after_until(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    orchestrator.source_specs_by_id = {
        "M001": FoodSourceSpec(
            id="M001",
            name="Industry source",
            url="https://example.com",
            adapter="rss",
            evidence_tier=EvidenceTier.INDUSTRY,
            collection_tier=CollectionTier.CORE,
            categories=[FoodCategory.PRODUCT_INNOVATION],
        )
    }
    orchestrator._food_analyzer = FakeAnalyzer()
    orchestrator._food_enricher = FakeEnricher()
    within = item("within", "Within")
    after = item("after", "After")
    within.published_at = datetime.fromisoformat(
        "2026-07-24T05:00:00+00:00"
    )
    after.published_at = datetime.fromisoformat(
        "2026-07-24T07:00:00+00:00"
    )
    for candidate in (within, after):
        candidate.metadata["food_source_id"] = "M001"
    observed_since = []

    async def fetch_all_sources(since):
        observed_since.append(since)
        orchestrator.last_fetch_report = FetchReport(
            [
                SourceFetchOutcome(
                    "M001",
                    "success",
                    items=[within, after],
                )
            ]
        )
        return [within, after]

    monkeypatch.setattr(
        orchestrator, "fetch_all_sources", fetch_all_sources
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run(
            since=datetime.fromisoformat(
                "2026-07-24T00:00:00+00:00"
            ),
            until=datetime.fromisoformat(
                "2026-07-24T06:00:00+00:00"
            ),
            deliver=False,
        )
    )

    assert observed_since[0].isoformat() == (
        "2026-07-24T00:00:00+00:00"
    )
    raw = orchestrator.run_store.load_stage(
        orchestrator.active_run_id, "raw"
    )
    assert [candidate.id for candidate in raw] == ["within"]
    manifest = orchestrator.run_store.load_manifest(
        orchestrator.active_run_id
    )
    assert manifest["run_window"] == {
        "since": "2026-07-24T00:00:00+00:00",
        "until": "2026-07-24T06:00:00+00:00",
    }


def test_resume_from_enriched_skips_completed_work(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    run_id = orchestrator.run_store.create_run("balanced")
    fixture = Path(
        "tests/fixtures/foodscope/selected_brief_facts.json"
    )
    fixture_path = Path(__file__).parents[2] / fixture
    payload = json.loads(
        fixture_path.read_text(encoding="utf-8")
    )
    candidate = ContentItem.model_validate(
        payload["must_read"][0]
    )
    for stage in (
        "raw",
        "normalized",
        "scored",
        "filtered",
        "enriched",
    ):
        orchestrator.run_store.save_stage(
            run_id, stage, [candidate]
        )
    orchestrator.run_store.set_run_window(
        run_id,
        datetime.fromisoformat(
            "2026-07-23T00:00:00+00:00"
        ),
        datetime.fromisoformat(
            "2026-07-24T06:00:00+00:00"
        ),
    )

    async def should_not_run(*args, **kwargs):
        raise AssertionError("completed stage ran again")

    monkeypatch.setattr(
        orchestrator, "fetch_all_sources", should_not_run
    )
    monkeypatch.setattr(
        orchestrator, "_analyze_content", should_not_run
    )
    monkeypatch.setattr(
        orchestrator,
        "_enrich_important_items",
        should_not_run,
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run(
            resume_run_id=run_id, deliver=False
        )
    )

    manifest = orchestrator.run_store.load_manifest(run_id)
    assert manifest["completed_stages"][-1] == "summary"
    assert manifest["facts_sha256"]


def test_resume_rejects_profile_mismatch(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    run_id = orchestrator.run_store.create_run("market")
    orchestrator.run_store.save_stage(
        run_id, "raw", [item("one", "One")]
    )

    try:
        asyncio.run(
            orchestrator.run(
                resume_run_id=run_id, deliver=False
            )
        )
    except ValueError as error:
        assert "profile" in str(error)
    else:
        raise AssertionError(
            "profile mismatch should reject resume"
        )
