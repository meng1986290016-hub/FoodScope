from datetime import datetime

import pytest

from src.foodscope.scheduler import (
    FoodScopeScheduler,
    RunLock,
    RunLockHeldError,
    check_schedule_health,
    resolve_run_window,
)
from src.foodscope.run_store import FoodRunStore, RunStage


def test_default_schedule_is_0630_shanghai():
    schedule = FoodScopeScheduler(
        timezone="Asia/Shanghai", cron="30 6 * * *"
    )
    current = datetime.fromisoformat(
        "2026-07-24T06:29:00+08:00"
    )

    assert schedule.next_after(current).isoformat() == (
        "2026-07-24T06:30:00+08:00"
    )


def test_schedule_respects_london_daylight_saving_transition():
    schedule = FoodScopeScheduler(
        timezone="Europe/London", cron="30 6 * * *"
    )
    current = datetime.fromisoformat(
        "2026-03-28T07:00:00+00:00"
    )

    assert schedule.next_after(current).isoformat() == (
        "2026-03-29T06:30:00+01:00"
    )


def test_invalid_cron_and_timezone_are_rejected():
    with pytest.raises(ValueError, match="cron"):
        FoodScopeScheduler(
            timezone="Asia/Shanghai", cron="not a cron"
        )
    with pytest.raises(ValueError, match="timezone"):
        FoodScopeScheduler(
            timezone="Mars/Olympus", cron="30 6 * * *"
        )


def test_explicit_window_requires_offsets_and_has_precedence():
    window = resolve_run_window(
        since="2026-07-23T00:00:00+08:00",
        until="2026-07-24T00:00:00+08:00",
        lookback_hours=30,
    )

    assert window.since.isoformat() == (
        "2026-07-23T00:00:00+08:00"
    )
    assert window.until.isoformat() == (
        "2026-07-24T00:00:00+08:00"
    )
    with pytest.raises(ValueError, match="explicit UTC offset"):
        resolve_run_window(
            since="2026-07-23T00:00:00",
            until="2026-07-24T00:00:00",
            lookback_hours=30,
        )


def test_run_window_rejects_invalid_duration():
    with pytest.raises(ValueError, match="positive"):
        resolve_run_window(
            since="2026-07-24T00:00:00+08:00",
            until="2026-07-23T00:00:00+08:00",
            lookback_hours=30,
        )
    with pytest.raises(ValueError, match="720"):
        resolve_run_window(
            hours=721,
            lookback_hours=30,
            now=datetime.fromisoformat(
                "2026-07-24T00:00:00+00:00"
            ),
        )


def test_two_lock_holders_cannot_enter_same_run(tmp_path):
    path = tmp_path / "state" / "foodscope.lock"
    first = RunLock(path)
    second = RunLock(path)

    first.acquire()
    try:
        with pytest.raises(
            RunLockHeldError, match=r"PID \d+.*started"
        ):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_healthcheck_detects_missing_recent_and_stale_runs(
    tmp_path,
):
    schedule = FoodScopeScheduler(
        timezone="Asia/Shanghai", cron="30 6 * * *"
    )
    now = datetime.fromisoformat(
        "2026-07-24T10:00:00+08:00"
    )
    store = FoodRunStore(tmp_path / "runs")

    missing = check_schedule_health(
        store.root, schedule, now
    )
    assert missing.healthy is False

    run_id = store.create_run("balanced")
    store.save_stage(
        run_id, RunStage.SUMMARY, {"markdown": "# ready"}
    )
    manifest = store.load_manifest(run_id)
    manifest["created_at"] = "2026-07-23T00:00:00+00:00"
    store._write_manifest(run_id, manifest)
    recent = check_schedule_health(
        store.root, schedule, now
    )
    assert recent.healthy is True

    manifest["created_at"] = "2026-07-20T00:00:00+00:00"
    store._write_manifest(run_id, manifest)
    stale = check_schedule_health(
        store.root, schedule, now
    )
    assert stale.healthy is False
    assert "overdue" in stale.detail
