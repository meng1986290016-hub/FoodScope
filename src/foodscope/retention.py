"""Bounded and symlink-safe retention for FoodScope run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


_STAGE_FILES = {
    "raw.json",
    "normalized.json",
    "scored.json",
    "filtered.json",
    "enriched.json",
}
_RETAINED_FILES = {
    "facts.json",
    "brief.md",
    "brief.html",
    "manifest.json",
    "summary.json",
}
_KNOWN_FILES = _STAGE_FILES | _RETAINED_FILES


@dataclass(frozen=True)
class RetentionResult:
    stage_files_removed: int = 0
    runs_removed: int = 0
    skipped_symlinks: int = 0


class RetentionPolicy:
    def __init__(
        self,
        *,
        stage_days: int = 30,
        brief_days: int = 180,
    ) -> None:
        if stage_days <= 0 or brief_days <= 0:
            raise ValueError(
                "retention days must be positive"
            )
        if stage_days > brief_days:
            raise ValueError(
                "stage retention cannot exceed brief retention"
            )
        self.stage_days = stage_days
        self.brief_days = brief_days

    def apply(
        self, runs_root: Path, now: datetime
    ) -> RetentionResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        root = Path(runs_root)
        if root.is_symlink():
            raise ValueError(
                "runs root cannot be a symlink"
            )
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve()
        stage_cutoff = now.astimezone(
            timezone.utc
        ) - timedelta(days=self.stage_days)
        brief_cutoff = now.astimezone(
            timezone.utc
        ) - timedelta(days=self.brief_days)
        stages_removed = 0
        runs_removed = 0
        skipped_symlinks = 0

        for run_dir in root.iterdir():
            if run_dir.is_symlink():
                skipped_symlinks += 1
                continue
            if not run_dir.is_dir():
                continue
            resolved_run = run_dir.resolve()
            if resolved_run.parent != resolved_root:
                continue

            for filename in _STAGE_FILES:
                path = run_dir / filename
                if (
                    not path.exists()
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    continue
                if self._modified_at(path) < stage_cutoff:
                    path.unlink()
                    stages_removed += 1

            children = list(run_dir.iterdir())
            if any(child.is_symlink() for child in children):
                skipped_symlinks += 1
                continue
            if any(
                not child.is_file()
                or child.name not in _KNOWN_FILES
                for child in children
            ):
                continue
            retained = [
                child
                for child in children
                if child.name in _RETAINED_FILES
            ]
            if not retained or not all(
                self._modified_at(path) < brief_cutoff
                for path in retained
            ):
                continue
            if not all(
                self._modified_at(path) < brief_cutoff
                for path in children
            ):
                continue
            for child in children:
                child.unlink()
            run_dir.rmdir()
            runs_removed += 1

        return RetentionResult(
            stage_files_removed=stages_removed,
            runs_removed=runs_removed,
            skipped_symlinks=skipped_symlinks,
        )

    @staticmethod
    def _modified_at(path: Path) -> datetime:
        return datetime.fromtimestamp(
            path.stat(follow_symlinks=False).st_mtime,
            tz=timezone.utc,
        )
