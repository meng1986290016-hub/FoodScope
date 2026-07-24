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

    assert manifest["schema_version"] == 1
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
    metric = {"source_id": "M001", "run_id": run_id}

    store.record_source_metrics(run_id, [metric])
    store.record_source_metrics(run_id, [metric])

    assert store.load_manifest(run_id)["source_metrics"] == [metric]


@pytest.mark.parametrize(
    "run_id", ["../outside", "../../etc", "nested/run"]
)
def test_run_store_rejects_traversal_ids(tmp_path, run_id):
    store = FoodRunStore(tmp_path / "runs")

    with pytest.raises(ValueError, match="run ID"):
        store.load_manifest(run_id)
