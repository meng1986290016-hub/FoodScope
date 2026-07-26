import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from src.ai.tokens import ProviderUsage, TokenUsageSnapshot
from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    RiskLevel,
)
from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.foodscope.run_store import RunStage
from src.foodscope.selector import SelectionResult
from src.models import Config, ContentItem
from src.orchestrator import FetchReport, SourceFetchOutcome
from src.storage.manager import StorageManager
from tests.foodscope.test_config_models import legacy_config
from tests.foodscope.test_normalizer import item
from tests.foodscope.test_selector import scored_item


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

    async def fetch_all_sources(since, until=None):
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
    usage_snapshots = iter(
        [
            TokenUsageSnapshot(
                total_input_tokens=1000,
                total_output_tokens=0,
                per_model={
                    "openai/gpt-4": ProviderUsage(
                        input_tokens=1000
                    )
                },
            ),
            TokenUsageSnapshot(
                total_input_tokens=1120,
                total_output_tokens=0,
                per_model={
                    "openai/gpt-4": ProviderUsage(
                        input_tokens=1120
                    )
                },
            ),
        ]
    )
    monkeypatch.setattr(
        "src.foodscope.orchestrator.get_usage_snapshot",
        lambda: next(usage_snapshots),
    )
    monotonic_snapshots = iter([100.0, 145.0])
    monkeypatch.setattr(
        "src.foodscope.orchestrator.monotonic",
        lambda: next(monotonic_snapshots),
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run(
            since=datetime.fromisoformat(
                "2026-07-24T00:00:00+00:00"
            ),
            until=datetime.fromisoformat(
                "2026-07-25T00:00:00+00:00"
            ),
        )
    )

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
    assert manifest["source_selection"] == ["M001"]
    assert manifest["eligible_sources"] == ["M001"]
    assert len(manifest["source_config_sha256"]) == 64
    assert manifest["source_outcomes"] == [
        {
            "source": "M001",
            "status": "success",
            "candidate_count": 2,
        }
    ]
    assert manifest["token_usage"]["total_tokens"] == 120
    assert manifest["token_usage"]["estimated_cost"] is None
    metric = manifest["source_metrics"][0]
    assert metric["source_id"] == "M001"
    assert metric["candidate_count"] == 2
    assert metric["food_relevant_count"] == 1
    assert metric["admitted_count"] == 1
    assert metric["ai_tokens"] == 120
    assert manifest["timing"] == {
        "duration_seconds": 45.0,
        "target_minutes": 60,
        "completed_within_target": True,
    }
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

    async def fetch_all_sources(since, until=None):
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


def test_summary_only_resume_does_not_overwrite_source_metrics(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    run_id = orchestrator.run_store.create_run("balanced")
    for stage in (
        RunStage.RAW,
        RunStage.NORMALIZED,
        RunStage.SCORED,
        RunStage.FILTERED,
        RunStage.ENRICHED,
    ):
        orchestrator.run_store.save_stage(run_id, stage, [])
    orchestrator.run_store.save_stage(
        run_id, RunStage.SUMMARY, {"markdown": "# ready"}
    )
    orchestrator.run_store.record_source_metrics(
        run_id,
        [
            {
                "run_id": run_id,
                "source_id": "M001",
                "admitted_count": 9,
                "unique_event_count": 7,
            }
        ],
    )
    called = False

    async def no_pipeline(**kwargs):
        return None

    def overwrite_metrics():
        nonlocal called
        called = True

    monkeypatch.setattr(
        orchestrator, "_run_foodscope_pipeline", no_pipeline
    )
    monkeypatch.setattr(
        orchestrator, "_record_source_metrics", overwrite_metrics
    )

    asyncio.run(
        orchestrator.run(
            resume_run_id=run_id, deliver=False
        )
    )

    assert called is False
    assert orchestrator.run_store.load_manifest(
        run_id
    )["source_metrics"][0]["admitted_count"] == 9


def test_resumed_metrics_use_persisted_outcomes_and_total_usage(
    tmp_path,
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    source_spec = FoodSourceSpec(
        id="M001",
        name="Industry source",
        url="https://example.com",
        adapter="rss",
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )
    rotated_source = source_spec.model_copy(
        update={
            "id": "M002",
            "name": "Rotated source",
            "url": "https://example.com/rotated",
        }
    )
    candidate = scored_item("metric", source_id="M001")
    run_id = orchestrator.run_store.create_run(
        "balanced", run_provenance="scheduled"
    )
    orchestrator.run_store.save_stage(
        run_id, RunStage.SCORED, [candidate]
    )
    orchestrator.run_store.record_source_outcomes(
        run_id,
        [
            {
                "source": "M001",
                "status": "success",
                "candidate_count": 1,
                "published_at_candidate_count": 1,
                "published_at_parse_count": 1,
            }
        ],
    )
    pricing = [
        {
            "route": "fast",
            "provider": "openai",
            "model": "gpt-4",
            "input_cost_per_million": 1.0,
            "output_cost_per_million": 2.0,
        }
    ]
    orchestrator.run_store.record_token_usage(
        run_id,
        input_tokens=100,
        output_tokens=20,
        per_model=[
            {
                "key": "openai/gpt-4",
                "provider": "openai",
                "model": "gpt-4",
                "input_tokens": 100,
                "output_tokens": 20,
            }
        ],
        pricing=pricing,
    )

    for extra_input in (0, 30):
        if extra_input:
            orchestrator.run_store.record_token_usage(
                run_id,
                input_tokens=extra_input,
                output_tokens=0,
                per_model=[
                    {
                        "key": "openai/gpt-4",
                        "provider": "openai",
                        "model": "gpt-4",
                        "input_tokens": extra_input,
                        "output_tokens": 0,
                    }
                ],
                pricing=pricing,
            )
        manifest = orchestrator.run_store.load_manifest(run_id)
        orchestrator.active_run_id = run_id
        orchestrator.source_specs_by_id = {
            "M001": source_spec,
            "M002": rotated_source,
        }
        orchestrator.last_fetch_report = (
            orchestrator._fetch_report_from_manifest(manifest)
        )
        orchestrator.selection_result = SelectionResult(
            items=[candidate]
        )
        orchestrator._record_source_metrics()

    metrics = orchestrator.run_store.load_manifest(
        run_id
    )["source_metrics"]
    metric = metrics[0]
    assert metric["ai_tokens"] == 150
    assert metric["estimated_cost"] == 0.00017
    assert metric["run_provenance"] == "scheduled"
    assert metrics[1]["source_id"] == "M002"
    assert metrics[1]["fetch_status"] == "skipped_rotation"
    assert metrics[1]["ai_tokens"] == 0
    assert metrics[1]["estimated_cost"] == 0.0


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


def test_resume_rejects_changed_source_configuration(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    source = FoodSourceSpec(
        id="M001",
        name="Original source",
        url="https://example.com/original",
        adapter="rss",
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )
    orchestrator.source_specs_by_id = {"M001": source}
    run_id = orchestrator.run_store.create_run("balanced")
    orchestrator.run_store.save_stage(
        run_id, RunStage.RAW, []
    )
    orchestrator.run_store.set_source_selection(
        run_id,
        ["M001"],
        eligible_source_ids=["M001"],
        source_config_sha256=(
            orchestrator._source_config_sha256()
        ),
    )
    orchestrator.source_specs_by_id["M002"] = source.model_copy(
        update={
            "id": "M002",
            "name": "New source",
            "url": "https://example.com/new",
        }
    )

    try:
        asyncio.run(
            orchestrator.run(
                resume_run_id=run_id, deliver=False
            )
        )
    except ValueError as error:
        assert "source configuration changed" in str(error)
    else:
        raise AssertionError(
            "source configuration drift should reject resume"
        )


def test_enrichment_failure_is_audited_but_excluded_from_brief(
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
    class UniqueEventAnalyzer(FakeAnalyzer):
        async def analyze_batch(self, items):
            analyzed = await super().analyze_batch(items)
            for candidate in analyzed:
                if candidate.food is not None:
                    candidate.food.event_key = (
                        f"{candidate.id}|unique-event"
                    )
            return analyzed

    orchestrator._food_analyzer = UniqueEventAnalyzer()
    raw_items = [
        item("enrichment-bad", "Must not enter brief"),
        item("enrichment-good", "Safe brief item"),
    ]
    for candidate in raw_items:
        candidate.metadata["food_source_id"] = "M001"

    class PartiallyFailingEnricher:
        async def enrich(self, items):
            for candidate in items:
                if candidate.id == "enrichment-bad":
                    candidate.metadata.update(
                        {
                            "foodscope_isolated": True,
                            "foodscope_isolation_stage": "enriched",
                            "foodscope_analysis_error": (
                                "FoodScope enrichment failed (ValueError)"
                            ),
                        }
                    )
                else:
                    assert candidate.food is not None
                    candidate.food.what_happened_zh = "安全内容。"
            return items

    orchestrator._food_enricher = PartiallyFailingEnricher()

    async def fetch_all_sources(since, until=None):
        orchestrator.last_fetch_report = FetchReport(
            [SourceFetchOutcome("M001", "success", items=raw_items)]
        )
        return raw_items

    monkeypatch.setattr(
        orchestrator, "fetch_all_sources", fetch_all_sources
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run(
            deliver=False,
            since=datetime.fromisoformat(
                "2026-07-24T00:00:00+00:00"
            ),
            until=datetime.fromisoformat(
                "2026-07-25T00:00:00+00:00"
            ),
        )
    )

    facts = json.loads(
        (
            storage.data_dir
            / "runs"
            / orchestrator.active_run_id
            / "facts.json"
        ).read_text(encoding="utf-8")
    )
    serialized = json.dumps(facts, ensure_ascii=False)
    assert "Safe brief item" in serialized
    assert "Must not enter brief" not in serialized
    manifest = orchestrator.run_store.load_manifest(
        orchestrator.active_run_id
    )
    assert any(
        entry["item_id"] == "enrichment-bad"
        and entry["stage"] == "enriched"
        for entry in manifest["isolation"]
    )

    class GenericNotifier:
        config = SimpleNamespace(
            enabled=True, platform="generic"
        )

        def __init__(self):
            self.item_ids = []

        def build_daily_summary_messages(
            self, *, important_items, **kwargs
        ):
            self.item_ids = [
                candidate.id
                for candidate in important_items
            ]
            return [{"message": "canonical"}]

        async def notify(self, message):
            return SimpleNamespace(sent=True)

    monkeypatch.chdir(Path(__file__).parents[2])
    resumed = FoodScopeOrchestrator(_config(), storage)
    resumed.source_specs_by_id = dict(
        orchestrator.source_specs_by_id
    )
    monkeypatch.chdir(tmp_path)
    notifier = GenericNotifier()
    resumed.webhook_notifier = notifier

    asyncio.run(
        resumed.run(
            resume_run_id=orchestrator.active_run_id,
            deliver=True,
        )
    )

    assert "enrichment-good" in notifier.item_ids
    assert "enrichment-bad" not in notifier.item_ids


def test_filtered_resume_restores_risk_alert_partition(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    regular = scored_item("regular")
    alert = scored_item("alert", risk_level=RiskLevel.HIGH)
    orchestrator.selection_result = SelectionResult(
        items=[regular], risk_alerts=[alert]
    )
    run_id = orchestrator.run_store.create_run("balanced")
    orchestrator.active_run_id = run_id
    for stage in (RunStage.RAW, RunStage.NORMALIZED, RunStage.SCORED):
        orchestrator.run_store.save_stage(
            run_id, stage, [regular, alert]
        )
    asyncio.run(orchestrator._on_stage("filtered", [regular]))
    orchestrator.run_store.set_run_window(
        run_id,
        datetime.fromisoformat("2026-07-23T00:00:00+00:00"),
        datetime.fromisoformat("2026-07-24T06:00:00+00:00"),
    )
    stored = orchestrator.run_store.load_stage(
        run_id, RunStage.FILTERED
    )
    assert isinstance(stored, list)
    assert {
        candidate.id: candidate.metadata.get("foodscope_risk_alert")
        for candidate in stored
    } == {
        regular.id: None,
        alert.id: True,
    }
    resumed = FoodScopeOrchestrator(_config(), storage)
    resumed._food_enricher = FakeEnricher()
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        resumed.run(resume_run_id=run_id, deliver=False)
    )

    facts = json.loads(
        (
            storage.data_dir / "runs" / run_id / "facts.json"
        ).read_text(encoding="utf-8")
    )
    assert facts["risk_alerts"] == []
    assert {
        entry["id"] for entry in facts["must_read"]
    } == {regular.id, alert.id}
    assert facts["news"] == []
    assert facts["sections"] == {}


def test_event_memory_is_written_only_after_filtered_stage_commit(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    candidate = scored_item("atomic")
    assert candidate.food is not None
    candidate.food.event_key = "atomic-event"
    run_id = orchestrator.run_store.create_run("balanced")
    orchestrator.active_run_id = run_id
    selected = orchestrator.apply_balanced_digest([candidate]).items
    original_save_stage = orchestrator.run_store.save_stage

    def fail_save(*args, **kwargs):
        raise OSError("simulated stage commit failure")

    monkeypatch.setattr(
        orchestrator.run_store, "save_stage", fail_save
    )
    try:
        asyncio.run(orchestrator._on_stage("filtered", selected))
    except OSError:
        pass
    else:
        raise AssertionError("filtered stage save should fail")

    assert not orchestrator.event_store.path.exists()
    monkeypatch.setattr(
        orchestrator.run_store, "save_stage", original_save_stage
    )
    asyncio.run(orchestrator._on_stage("filtered", selected))
    assert "atomic-event" in orchestrator.event_store.path.read_text(
        encoding="utf-8"
    )


def test_evidence_rejection_is_recorded_in_isolation_audit(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)
    rejected = scored_item(
        "unverified-recall",
        category=FoodCategory.FOOD_SAFETY_RECALLS,
        evidence_tier=EvidenceTier.INDUSTRY,
    )
    run_id = orchestrator.run_store.create_run("balanced")
    orchestrator.active_run_id = run_id
    messages = []
    orchestrator.console = SimpleNamespace(
        print=lambda message: messages.append(message)
    )

    result = asyncio.run(
        orchestrator.filter_items(
            [rejected], apply_balance=False
        )
    )

    assert result.items == []
    assert rejected.metadata["foodscope_admission_mode"] == "loose"
    assert rejected.metadata["foodscope_admission_reason"] == (
        "official evidence required"
    )
    manifest = orchestrator.run_store.load_manifest(run_id)
    assert manifest["evidence_admission"][
        "rejected_official_evidence_required"
    ] == 1
    assert any(
        "Evidence admission" in message for message in messages
    )
    assert any(
        "rejected_official_evidence_required=1" in message
        for message in messages
    )
    assert manifest["isolation"] == [
        {
            "item_id": rejected.id,
            "stage": "filtered",
            "error": "evidence rejected: official evidence required",
        }
    ]


def test_business_date_uses_configured_schedule_timezone(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)

    assert orchestrator._business_date(
        datetime.fromisoformat("2026-07-23T18:30:00+00:00")
    ) == "2026-07-24"


def test_failure_webhook_receives_only_sanitized_error(
    tmp_path, monkeypatch
):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = FoodScopeOrchestrator(_config(), storage)

    class FailureNotifier:
        def __init__(self):
            self.error_message = None

        async def send_failure(self, date, error_message):
            self.error_message = error_message

    notifier = FailureNotifier()
    orchestrator.webhook_notifier = notifier

    async def fail_fetch(since, until=None):
        raise RuntimeError(
            "https://provider.test?access_token=failure-secret"
        )

    monkeypatch.setattr(
        orchestrator, "fetch_all_sources", fail_fetch
    )

    try:
        asyncio.run(orchestrator.run())
    except RuntimeError:
        pass
    else:
        raise AssertionError("source failure should be re-raised")

    assert notifier.error_message == (
        "FoodScope generation failed (RuntimeError)"
    )
    assert "failure-secret" not in notifier.error_message
