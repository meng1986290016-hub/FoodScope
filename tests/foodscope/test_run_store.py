import pytest

from src.foodscope.run_store import FoodRunStore, RunStage
from tests.foodscope.test_normalizer import item


def test_stage_round_trip_and_resume(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    store.save_stage(run_id, RunStage.RAW, [item("one", "Title")])

    restored = store.load_stage(run_id, RunStage.RAW)

    assert restored[0].id == "one"
    assert store.latest_resumable_run() == (run_id, RunStage.RAW)


def test_summary_payload_round_trips_without_content_item_conversion(
    tmp_path,
):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="market")

    store.save_stage(
        run_id,
        RunStage.SUMMARY,
        {"markdown": "# 简报", "fact_hash": "sha256:test"},
    )

    assert store.load_stage(run_id, RunStage.SUMMARY) == {
        "markdown": "# 简报",
        "fact_hash": "sha256:test",
    }
    assert store.latest_resumable_run() is None


def test_manifest_tracks_stage_counts_and_isolation(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    isolated = item("bad", "Bad")
    isolated.metadata.update(
        {
            "foodscope_isolated": True,
            "foodscope_analysis_error": "invalid JSON",
        }
    )

    store.save_stage(
        run_id, RunStage.SCORED, [item("good", "Good"), isolated]
    )
    manifest = store.load_manifest(run_id)

    assert manifest["schema_version"] == 3
    assert manifest["profile_id"] == "balanced"
    assert manifest["completed_stages"] == ["scored"]
    assert manifest["counts"]["scored"] == 2
    assert manifest["isolation"] == [
        {
            "item_id": "bad",
            "stage": "scored",
            "error": "invalid JSON",
        }
    ]
    assert manifest["errors"] == []
    assert manifest["token_usage"] == {}
    assert manifest["evidence_admission"] == {
        "mode": "loose",
        "accepted_authoritative": 0,
        "accepted_corroborated": 0,
        "accepted_single_source": 0,
        "accepted_aggregator_fallback": 0,
        "rejected_not_relevant": 0,
        "rejected_official_evidence_required": 0,
        "rejected_unknown_publisher": 0,
        "rejected_strict_evidence": 0,
        "rejected_other": 0,
    }


def test_new_manifest_records_configured_evidence_mode(tmp_path):
    store = FoodRunStore(tmp_path)

    run_id = store.create_run(
        profile_id="balanced",
        evidence_mode="strict",
    )

    assert store.load_manifest(run_id)["evidence_admission"][
        "mode"
    ] == "strict"


def test_stage_and_manifest_writes_leave_no_temporary_sibling(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="rd")

    store.save_stage(run_id, RunStage.RAW, [item("one", "Title")])

    run_dir = tmp_path / run_id
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "manifest.json",
        "raw.json",
    ]


def test_delivery_records_are_idempotent(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")

    store.record_delivery(
        run_id, "email", "success", artifact_id="sha256:test"
    )
    store.record_delivery(
        run_id, "email", "success", artifact_id="sha256:test"
    )

    delivery = store.load_manifest(run_id)["deliveries"]["email"]
    assert delivery["attempts"] == 1
    assert len(delivery["records"]) == 1


def test_failed_delivery_can_retry_same_artifact(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")

    store.record_delivery(
        run_id, "email", "failed", artifact_id="sha256:test"
    )
    store.record_delivery(
        run_id, "email", "success", artifact_id="sha256:test"
    )

    delivery = store.load_manifest(run_id)["deliveries"]["email"]
    assert delivery["attempts"] == 2
    assert delivery["status"] == "success"


def test_source_metrics_are_idempotent_per_run_and_source(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    metric = {
        "source_id": "M001",
        "run_id": run_id,
        "candidate_count": 1,
    }
    updated = {
        "source_id": "M001",
        "run_id": run_id,
        "candidate_count": 2,
    }

    store.record_source_metrics(run_id, [metric])
    store.record_source_metrics(run_id, [updated])

    assert store.load_manifest(run_id)["source_metrics"] == [
        updated
    ]


def test_evidence_admission_summary_is_persisted_idempotently(
    tmp_path,
):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    first = {
        "mode": "loose",
        "accepted_single_source": 2,
        "rejected_official_evidence_required": 1,
    }
    updated = {
        "mode": "loose",
        "accepted_single_source": 3,
        "rejected_official_evidence_required": 1,
    }

    store.record_evidence_admission(run_id, first)
    store.record_evidence_admission(run_id, updated)

    assert store.load_manifest(run_id)["evidence_admission"] == (
        updated
    )


def test_source_selection_is_ordered_deduplicated_and_persisted(
    tmp_path,
):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(
        profile_id="balanced",
        run_provenance="scheduled",
    )

    store.set_source_selection(
        run_id,
        ["M002", "M001", "M002"],
        eligible_source_ids=["M001", "M002", "M001"],
        source_config_sha256="abc123",
    )

    manifest = store.load_manifest(run_id)
    assert manifest["run_provenance"] == "scheduled"
    assert manifest["source_selection"] == ["M002", "M001"]
    assert manifest["eligible_sources"] == ["M001", "M002"]
    assert manifest["source_config_sha256"] == "abc123"


def test_source_outcomes_and_token_usage_survive_resume(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    store.record_source_outcomes(
        run_id,
        [
            {
                "source": "M001",
                "status": "success",
                "item_count": 2,
                "candidate_count": 2,
                "published_at_candidate_count": 2,
                "published_at_parse_count": 1,
                "ignored": "not persisted",
            }
        ],
    )
    pricing = [
        {
            "route": "fast",
            "provider": "openai",
            "model": "gpt-test",
            "input_cost_per_million": 2.0,
            "output_cost_per_million": 4.0,
        }
    ]
    store.record_token_usage(
        run_id,
        input_tokens=100,
        output_tokens=50,
        per_model=[
            {
                "key": "openai/gpt-test",
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 100,
                "output_tokens": 50,
            }
        ],
        pricing=pricing,
    )
    store.record_token_usage(
        run_id,
        input_tokens=20,
        output_tokens=10,
        per_model=[
            {
                "key": "openai/gpt-test",
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 20,
                "output_tokens": 10,
            }
        ],
        pricing=pricing,
    )

    manifest = store.load_manifest(run_id)
    assert manifest["source_outcomes"] == [
        {
            "source": "M001",
            "status": "success",
            "candidate_count": 2,
            "published_at_candidate_count": 2,
            "published_at_parse_count": 1,
        }
    ]
    assert manifest["token_usage"]["input_tokens"] == 120
    assert manifest["token_usage"]["output_tokens"] == 60
    assert manifest["token_usage"]["total_tokens"] == 180
    assert (
        manifest["token_usage"]["per_model"]
        ["openai/gpt-test"]["total_tokens"]
        == 180
    )
    assert manifest["token_usage"]["estimated_cost"] == 0.00048
    assert manifest["token_usage"]["unpriced_models"] == []


def test_unconfigured_model_price_is_not_reported_as_zero(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")

    store.record_token_usage(
        run_id,
        input_tokens=10,
        output_tokens=5,
        per_model=[
            {
                "key": "openai/gpt-test",
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 10,
                "output_tokens": 5,
            }
        ],
        pricing=[],
    )

    usage = store.load_manifest(run_id)["token_usage"]
    assert usage["estimated_cost"] is None
    assert usage["unpriced_models"] == ["openai/gpt-test"]


def test_run_timing_records_target_service_level(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")

    store.record_timing(
        run_id,
        duration_seconds=3660.0,
        target_minutes=60,
    )
    store.record_timing(
        run_id,
        duration_seconds=1.0,
        target_minutes=60,
    )

    assert store.load_manifest(run_id)["timing"] == {
        "duration_seconds": 3660.0,
        "target_minutes": 60,
        "completed_within_target": False,
    }


@pytest.mark.parametrize(
    "run_id", ["../outside", "../../etc", "nested/run"]
)
def test_run_store_rejects_traversal_ids(tmp_path, run_id):
    store = FoodRunStore(tmp_path / "runs")

    with pytest.raises(ValueError, match="run ID"):
        store.load_manifest(run_id)
