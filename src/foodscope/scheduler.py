"""Timezone-aware scheduling, run windows, and process locking."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict


class RunWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    since: datetime
    until: datetime


def _offset_datetime(
    value: str | datetime, name: str
) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise ValueError(
                f"{name} must be RFC 3339"
            ) from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError(
            f"{name} must include an explicit UTC offset"
        )
    return parsed


def resolve_run_window(
    *,
    hours: int | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    lookback_hours: int,
    now: datetime | None = None,
) -> RunWindow:
    """Resolve an explicit, relative, or configured collection window."""
    if hours is not None and (
        since is not None or until is not None
    ):
        raise ValueError(
            "hours and an explicit window are mutually exclusive"
        )
    if (since is None) != (until is None):
        raise ValueError(
            "since and until must be provided together"
        )
    if since is not None and until is not None:
        start = _offset_datetime(since, "since")
        end = _offset_datetime(until, "until")
    else:
        end = now or datetime.now(timezone.utc)
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        duration_hours = (
            hours if hours is not None else lookback_hours
        )
        if duration_hours <= 0:
            raise ValueError(
                "collection window must be positive"
            )
        if duration_hours > 720:
            raise ValueError(
                "collection window cannot exceed 720 hours"
            )
        start = end - timedelta(hours=duration_hours)

    duration = end.astimezone(timezone.utc) - start.astimezone(
        timezone.utc
    )
    if duration <= timedelta(0):
        raise ValueError(
            "collection window must be positive"
        )
    if duration > timedelta(hours=720):
        raise ValueError(
            "collection window cannot exceed 720 hours"
        )
    return RunWindow(since=start, until=end)


class FoodScopeScheduler:
    """Calculate and execute cron occurrences in one IANA timezone."""

    def __init__(self, *, timezone: str, cron: str) -> None:
        try:
            self.timezone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                f"invalid schedule timezone: {timezone}"
            ) from error
        if not croniter.is_valid(cron):
            raise ValueError(
                f"invalid schedule cron expression: {cron}"
            )
        self.cron = cron

    def next_after(self, current: datetime) -> datetime:
        if (
            current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise ValueError(
                "scheduler current time must be timezone-aware"
            )
        local = current.astimezone(self.timezone)
        return croniter(
            self.cron, local
        ).get_next(datetime).astimezone(self.timezone)

    def previous_before(self, current: datetime) -> datetime:
        if (
            current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise ValueError(
                "scheduler current time must be timezone-aware"
            )
        local = current.astimezone(self.timezone)
        return croniter(
            self.cron, local
        ).get_prev(datetime).astimezone(self.timezone)

    async def run_forever(
        self,
        run_once: Callable[[], Awaitable[Any]],
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        """Wait for each occurrence and invoke the normal one-run path."""
        clock = now or (
            lambda: datetime.now(timezone.utc)
        )
        while True:
            current = clock()
            next_run = self.next_after(current)
            delay = max(
                0.0,
                (
                    next_run.astimezone(timezone.utc)
                    - current.astimezone(timezone.utc)
                ).total_seconds(),
            )
            await sleep(delay)
            await run_once()


class ScheduleHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    healthy: bool
    detail: str
    latest_run_at: datetime | None = None
    overdue_threshold: datetime | None = None


def check_schedule_health(
    runs_root: Path,
    scheduler: FoodScopeScheduler,
    now: datetime | None = None,
) -> ScheduleHealth:
    """Check whether a completed run is over two cron intervals late."""
    current = now or datetime.now(timezone.utc)
    if (
        current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise ValueError(
            "healthcheck time must be timezone-aware"
        )
    latest_due = scheduler.previous_before(
        current + timedelta(microseconds=1)
    )
    threshold = latest_due
    for _ in range(2):
        threshold = scheduler.previous_before(threshold)

    latest: datetime | None = None
    root = Path(runs_root)
    if root.exists() and not root.is_symlink():
        for run_dir in root.iterdir():
            manifest_path = run_dir / "manifest.json"
            if (
                run_dir.is_symlink()
                or not run_dir.is_dir()
                or not manifest_path.is_file()
                or manifest_path.is_symlink()
            ):
                continue
            try:
                manifest = json.loads(
                    manifest_path.read_text(
                        encoding="utf-8"
                    )
                )
                if "summary" not in manifest.get(
                    "completed_stages", []
                ):
                    continue
                created = datetime.fromisoformat(
                    manifest["created_at"]
                )
                if (
                    created.tzinfo is None
                    or created.utcoffset() is None
                ):
                    continue
            except (
                OSError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                continue
            if latest is None or created > latest:
                latest = created

    threshold_utc = threshold.astimezone(timezone.utc)
    if latest is None:
        return ScheduleHealth(
            healthy=False,
            detail="no completed FoodScope run found",
            overdue_threshold=threshold,
        )
    if latest.astimezone(timezone.utc) < threshold_utc:
        return ScheduleHealth(
            healthy=False,
            detail=(
                "latest completed FoodScope run is overdue "
                "by more than two schedule intervals"
            ),
            latest_run_at=latest,
            overdue_threshold=threshold,
        )
    return ScheduleHealth(
        healthy=True,
        detail="latest completed FoodScope run is on schedule",
        latest_run_at=latest,
        overdue_threshold=threshold,
    )


class RunLockHeldError(RuntimeError):
    exit_code = 75


class RunLock:
    """Non-blocking advisory lock with operator-readable metadata."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(
            parents=True, exist_ok=True
        )
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_descriptor = os.open(
            self.path, flags, 0o600
        )
        handle = os.fdopen(
            file_descriptor, "r+", encoding="utf-8"
        )
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            handle.seek(0)
            raw = handle.read()
            handle.close()
            try:
                metadata = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            pid = metadata.get("pid", "unknown")
            started = metadata.get(
                "started_at", "unknown"
            )
            raise RunLockHeldError(
                "FoodScope is already running "
                f"(PID {pid}, started {started})"
            ) from error

        metadata = {
            "pid": os.getpid(),
            "started_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(metadata, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(
            self._handle.fileno(), fcntl.LOCK_UN
        )
        self._handle.close()
        self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False
