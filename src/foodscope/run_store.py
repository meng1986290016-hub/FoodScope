"""Atomic, resumable stage storage for FoodScope runs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.models import ContentItem


class RunStage(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    SCORED = "scored"
    FILTERED = "filtered"
    ENRICHED = "enriched"
    SUMMARY = "summary"


_ITEM_STAGES = {
    RunStage.RAW,
    RunStage.NORMALIZED,
    RunStage.SCORED,
    RunStage.FILTERED,
    RunStage.ENRICHED,
}
_STAGE_ORDER = {stage: index for index, stage in enumerate(RunStage)}


class FoodRunStore:
    """Persist canonical stage snapshots and delivery attempts."""

    SCHEMA_VERSION = 1

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, profile_id: str) -> str:
        now = self._now()
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + "-"
            + uuid4().hex[:8]
        )
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        self._write_manifest(
            run_id,
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "schema_version": self.SCHEMA_VERSION,
                "created_at": now,
                "updated_at": now,
                "completed_stages": [],
                "counts": {},
                "errors": [],
                "isolation": [],
                "token_usage": {},
                "source_metrics": [],
                "deliveries": {},
            },
        )
        return run_id

    def save_stage(
        self,
        run_id: str,
        stage: RunStage,
        payload: list[ContentItem] | dict | str,
    ) -> None:
        stage = RunStage(stage)
        if stage in _ITEM_STAGES:
            if not isinstance(payload, list) or not all(
                isinstance(item, ContentItem) for item in payload
            ):
                raise TypeError(
                    f"{stage.value} stage requires ContentItem list"
                )
            serialized: Any = [
                item.model_dump(mode="json") for item in payload
            ]
        else:
            if not isinstance(payload, (dict, str)):
                raise TypeError(
                    "summary stage requires a dictionary or string"
                )
            serialized = payload

        stage_path = self._run_dir(run_id) / f"{stage.value}.json"
        self._atomic_json_write(stage_path, serialized)

        manifest = self.load_manifest(run_id)
        if stage.value not in manifest["completed_stages"]:
            manifest["completed_stages"].append(stage.value)
        manifest["counts"][stage.value] = (
            len(payload) if isinstance(payload, list) else 1
        )
        if isinstance(payload, list):
            existing = {
                (entry["item_id"], entry["stage"])
                for entry in manifest["isolation"]
            }
            for item in payload:
                if not item.metadata.get("foodscope_isolated"):
                    continue
                key = (item.id, stage.value)
                if key in existing:
                    continue
                manifest["isolation"].append(
                    {
                        "item_id": item.id,
                        "stage": stage.value,
                        "error": item.metadata.get(
                            "foodscope_analysis_error", "isolated"
                        ),
                    }
                )
                existing.add(key)
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def load_stage(
        self, run_id: str, stage: RunStage
    ) -> list[ContentItem] | dict | str:
        stage = RunStage(stage)
        path = self._run_dir(run_id) / f"{stage.value}.json"
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if stage in _ITEM_STAGES:
            if not isinstance(payload, list):
                raise ValueError(
                    f"stored {stage.value} stage is not an item list"
                )
            return [ContentItem.model_validate(item) for item in payload]
        return payload

    def load_manifest(self, run_id: str) -> dict[str, Any]:
        path = self._run_dir(run_id) / "manifest.json"
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def latest_resumable_run(
        self,
    ) -> tuple[str, RunStage] | None:
        candidates: list[tuple[str, str, RunStage]] = []
        for run_dir in self.root.iterdir():
            if not run_dir.is_dir():
                continue
            try:
                manifest = self.load_manifest(run_dir.name)
                completed = {
                    RunStage(stage)
                    for stage in manifest.get("completed_stages", [])
                }
            except (
                FileNotFoundError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                continue
            if not completed or RunStage.SUMMARY in completed:
                continue
            latest_stage = max(
                completed, key=lambda stage: _STAGE_ORDER[stage]
            )
            candidates.append(
                (
                    manifest.get("updated_at", ""),
                    run_dir.name,
                    latest_stage,
                )
            )
        if not candidates:
            return None
        _, run_id, stage = max(candidates, key=lambda value: value[:2])
        return run_id, stage

    def record_delivery(
        self,
        run_id: str,
        channel: str,
        status: str,
        *,
        artifact_id: str,
        external_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        manifest = self.load_manifest(run_id)
        delivery = manifest["deliveries"].setdefault(
            channel,
            {
                "attempts": 0,
                "status": None,
                "artifact_id": None,
                "records": [],
            },
        )
        if any(
            record["status"] == "success"
            and record["artifact_id"] == artifact_id
            for record in delivery["records"]
        ):
            return

        attempted_at = self._now()
        delivery["attempts"] += 1
        delivery["status"] = status
        delivery["artifact_id"] = artifact_id
        delivery["updated_at"] = attempted_at
        delivery["records"].append(
            {
                "status": status,
                "artifact_id": artifact_id,
                "attempted_at": attempted_at,
                "external_id": external_id,
                "detail": detail,
            }
        )
        manifest["updated_at"] = attempted_at
        self._write_manifest(run_id, manifest)

    def delivery_succeeded(
        self,
        run_id: str,
        channel: str,
        artifact_id: str,
    ) -> bool:
        """Return whether this exact artifact already reached a channel."""
        manifest = self.load_manifest(run_id)
        delivery = manifest.get("deliveries", {}).get(channel, {})
        return any(
            record.get("status") == "success"
            and record.get("artifact_id") == artifact_id
            for record in delivery.get("records", [])
        )

    def record_source_metrics(
        self, run_id: str, metrics: list[dict[str, Any]]
    ) -> None:
        """Append sanitized source metrics once per run/source pair."""
        manifest = self.load_manifest(run_id)
        stored = manifest.setdefault("source_metrics", [])
        existing = {
            (metric.get("run_id"), metric.get("source_id"))
            for metric in stored
        }
        for metric in metrics:
            key = (metric.get("run_id"), metric.get("source_id"))
            if key in existing:
                continue
            stored.append(metric)
            existing.add(key)
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def save_brief_artifacts(
        self, run_id: str, facts, rendered
    ) -> None:
        """Atomically persist canonical facts and both render formats."""
        run_dir = self._run_dir(run_id)
        self._atomic_json_write(
            run_dir / "facts.json",
            json.loads(facts.canonical_json()),
        )
        self._atomic_text_write(
            run_dir / "brief.md", rendered.markdown
        )
        self._atomic_text_write(
            run_dir / "brief.html", rendered.html
        )
        manifest = self.load_manifest(run_id)
        manifest["facts_sha256"] = rendered.facts_sha256
        manifest["artifacts"] = {
            "facts": "facts.json",
            "markdown": "brief.md",
            "html": "brief.html",
        }
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def _run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        if not path.is_dir():
            raise FileNotFoundError(f"unknown FoodScope run: {run_id}")
        return path

    def _write_manifest(
        self, run_id: str, manifest: dict[str, Any]
    ) -> None:
        self._atomic_json_write(
            self._run_dir(run_id) / "manifest.json", manifest
        )

    @staticmethod
    def _atomic_json_write(path: Path, payload: Any) -> None:
        temporary = path.with_name(
            f".{path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_text_write(path: Path, content: str) -> None:
        temporary = path.with_name(
            f".{path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
