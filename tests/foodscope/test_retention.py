import os
from datetime import datetime, timedelta, timezone

from src.foodscope.retention import RetentionPolicy
from src.foodscope.run_store import FoodRunStore, RunStage
from tests.foodscope.test_normalizer import item


NOW = datetime(
    2026, 7, 24, 12, 0, tzinfo=timezone.utc
)


def _set_age(path, days):
    timestamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_old_stage_files_are_removed_but_briefs_are_retained(
    tmp_path,
):
    runs_root = tmp_path / "runs"
    store = FoodRunStore(runs_root)
    run_id = store.create_run("balanced")
    store.save_stage(
        run_id, RunStage.RAW, [item("one", "One")]
    )
    run_dir = runs_root / run_id
    facts = run_dir / "facts.json"
    facts.write_text("{}", encoding="utf-8")
    _set_age(run_dir / "raw.json", 31)
    _set_age(facts, 31)

    result = RetentionPolicy().apply(runs_root, NOW)

    assert not (run_dir / "raw.json").exists()
    assert facts.exists()
    assert result.stage_files_removed == 1
    assert result.runs_removed == 0


def test_run_is_removed_only_after_all_retained_artifacts_expire(
    tmp_path,
):
    runs_root = tmp_path / "runs"
    store = FoodRunStore(runs_root)
    run_id = store.create_run("balanced")
    run_dir = runs_root / run_id
    for name in ("facts.json", "brief.md", "brief.html"):
        path = run_dir / name
        path.write_text("old", encoding="utf-8")
        _set_age(path, 181)
    _set_age(run_dir / "manifest.json", 181)

    result = RetentionPolicy().apply(runs_root, NOW)

    assert not run_dir.exists()
    assert result.runs_removed == 1


def test_retention_never_follows_symlinks_outside_root(tmp_path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "brief.md"
    secret.write_text("keep", encoding="utf-8")
    _set_age(secret, 500)
    (runs_root / "linked-run").symlink_to(
        outside, target_is_directory=True
    )

    result = RetentionPolicy().apply(runs_root, NOW)

    assert secret.read_text(encoding="utf-8") == "keep"
    assert result.skipped_symlinks == 1

