"""Atomic, resumable stage storage for FoodScope runs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from src.foodscope.evidence import summarize_evidence_decisions
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

    SCHEMA_VERSION = 3

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        profile_id: str,
        *,
        run_provenance: str = "manual",
        evidence_mode: Literal["loose", "strict"] = "loose",
    ) -> str:
        if run_provenance not in {"manual", "scheduled"}:
            raise ValueError(
                "run_provenance must be manual or scheduled"
            )
        if evidence_mode not in {"loose", "strict"}:
            raise ValueError(
                "evidence_mode must be loose or strict"
            )
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
                "run_provenance": run_provenance,
                "schema_version": self.SCHEMA_VERSION,
                "created_at": now,
                "updated_at": now,
                "completed_stages": [],
                "counts": {},
                "errors": [],
                "isolation": [],
                "token_usage": {},
                "source_selection": [],
                "eligible_sources": [],
                "source_config_sha256": None,
                "source_outcomes": [],
                "source_metrics": [],
                "deliveries": {},
                "timing": {},
                "evidence_admission": (
                    summarize_evidence_decisions(
                        evidence_mode, []
                    )
                ),
            },
        )
        return run_id

    def set_source_selection(
        self,
        run_id: str,
        source_ids: list[str],
        *,
        eligible_source_ids: list[str] | None = None,
        source_config_sha256: str | None = None,
    ) -> None:
        """Persist the exact ordered source subset for this run."""
        manifest = self.load_manifest(run_id)
        manifest["source_selection"] = list(dict.fromkeys(source_ids))
        if eligible_source_ids is not None:
            manifest["eligible_sources"] = list(
                dict.fromkeys(eligible_source_ids)
            )
        if source_config_sha256 is not None:
            manifest["source_config_sha256"] = (
                source_config_sha256
            )
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def record_source_outcomes(
        self, run_id: str, outcomes: list[dict[str, Any]]
    ) -> None:
        """Persist bounded source telemetry needed after resume."""
        allowed = {
            "source",
            "status",
            "error",
            "candidate_count",
            "published_at_candidate_count",
            "published_at_parse_count",
            "window_since",
            "window_until",
        }
        sanitized = [
            {
                key: value
                for key, value in outcome.items()
                if key in allowed
            }
            for outcome in outcomes
        ]
        manifest = self.load_manifest(run_id)
        manifest["source_outcomes"] = sanitized
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def record_evidence_admission(
        self,
        run_id: str,
        summary: dict[str, str | int],
    ) -> None:
        """Persist one deterministic evidence-admission summary."""
        mode = summary.get("mode")
        if mode not in {"loose", "strict"}:
            raise ValueError(
                "evidence admission mode must be loose or strict"
            )
        sanitized: dict[str, str | int] = {"mode": str(mode)}
        for key, value in summary.items():
            if key == "mode":
                continue
            count = int(value)
            if count < 0:
                raise ValueError(
                    "evidence admission counts cannot be negative"
                )
            sanitized[str(key)] = count
        manifest = self.load_manifest(run_id)
        manifest["evidence_admission"] = sanitized
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def record_token_usage(
        self,
        run_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        per_model: list[dict[str, Any]],
        pricing: list[dict[str, Any]],
    ) -> None:
        """Add one invocation's model usage and recompute cost."""
        manifest = self.load_manifest(run_id)
        usage = manifest.get("token_usage") or {}
        usage["input_tokens"] = int(
            usage.get("input_tokens", 0)
        ) + max(0, int(input_tokens))
        usage["output_tokens"] = int(
            usage.get("output_tokens", 0)
        ) + max(0, int(output_tokens))
        usage["total_tokens"] = (
            usage["input_tokens"] + usage["output_tokens"]
        )
        stored_models = usage.setdefault("per_model", {})
        for row in per_model:
            key = str(row["key"])
            stored = stored_models.setdefault(
                key,
                {
                    "provider": str(row["provider"]),
                    "model": str(row["model"]),
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            stored["input_tokens"] += max(
                0, int(row.get("input_tokens", 0))
            )
            stored["output_tokens"] += max(
                0, int(row.get("output_tokens", 0))
            )
            stored["total_tokens"] = (
                stored["input_tokens"]
                + stored["output_tokens"]
            )
        if "pricing" not in usage:
            usage["pricing"] = pricing
        pricing = usage["pricing"]

        price_by_key = {
            f"{row['provider']}/{row['model']}": row
            for row in pricing
            if row.get("input_cost_per_million") is not None
            and row.get("output_cost_per_million") is not None
        }
        unpriced: list[str] = []
        estimated_cost = 0.0
        for key, row in stored_models.items():
            price = price_by_key.get(key)
            if price is None:
                if row.get("total_tokens", 0):
                    unpriced.append(key)
                continue
            estimated_cost += (
                row["input_tokens"]
                * float(price["input_cost_per_million"])
                + row["output_tokens"]
                * float(price["output_cost_per_million"])
            ) / 1_000_000
        attributed_tokens = sum(
            int(row.get("total_tokens", 0))
            for row in stored_models.values()
        )
        if attributed_tokens < usage["total_tokens"]:
            unpriced.append("__unattributed__")
        usage["unpriced_models"] = sorted(set(unpriced))
        usage["estimated_cost"] = (
            None
            if usage["unpriced_models"]
            else round(estimated_cost, 8)
        )
        manifest["token_usage"] = usage
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

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

    def record_isolation(
        self,
        run_id: str,
        *,
        item_id: str,
        stage: RunStage,
        error: str,
    ) -> None:
        """Record a bounded item-level rejection not present in a snapshot."""

        manifest = self.load_manifest(run_id)
        stage_value = RunStage(stage).value
        if any(
            entry.get("item_id") == item_id
            and entry.get("stage") == stage_value
            for entry in manifest["isolation"]
        ):
            return
        manifest["isolation"].append(
            {
                "item_id": item_id,
                "stage": stage_value,
                "error": error,
            }
        )
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

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

    def latest_run(self) -> str | None:
        """Return the newest valid run, including completed runs."""
        candidates: list[tuple[str, str]] = []
        for run_dir in self.root.iterdir():
            if not run_dir.is_dir() or run_dir.is_symlink():
                continue
            try:
                manifest = self.load_manifest(run_dir.name)
            except (
                FileNotFoundError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                continue
            candidates.append(
                (
                    manifest.get("updated_at", ""),
                    run_dir.name,
                )
            )
        if not candidates:
            return None
        return max(candidates)[1]

    def set_run_window(
        self,
        run_id: str,
        since: datetime,
        until: datetime,
    ) -> None:
        """Persist the exact collection window before fetching."""
        if (
            since.tzinfo is None
            or until.tzinfo is None
            or since.utcoffset() is None
            or until.utcoffset() is None
        ):
            raise ValueError(
                "run window must be timezone-aware"
            )
        if since >= until:
            raise ValueError(
                "run window must be positive"
            )
        manifest = self.load_manifest(run_id)
        manifest["run_window"] = {
            "since": since.isoformat(),
            "until": until.isoformat(),
        }
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def load_brief_artifacts(
        self, run_id: str
    ) -> tuple[Any, Any]:
        """Load and validate canonical facts and both render formats."""
        from .briefing import BriefFacts, RenderedBrief

        run_dir = self._run_dir(run_id)
        facts = BriefFacts.model_validate_json(
            (run_dir / "facts.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = self.load_manifest(run_id)
        rendered = RenderedBrief(
            facts_sha256=manifest["facts_sha256"],
            markdown=(run_dir / "brief.md").read_text(
                encoding="utf-8"
            ),
            html=(run_dir / "brief.html").read_text(
                encoding="utf-8"
            ),
        )
        if facts.fact_hash() != rendered.facts_sha256:
            raise ValueError(
                "stored brief fact hash does not match facts.json"
            )
        return facts, rendered

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
        """Upsert sanitized source metrics per run/source pair."""
        manifest = self.load_manifest(run_id)
        stored = manifest.setdefault("source_metrics", [])
        positions = {
            (metric.get("run_id"), metric.get("source_id")): index
            for index, metric in enumerate(stored)
        }
        for metric in metrics:
            key = (metric.get("run_id"), metric.get("source_id"))
            if key in positions:
                stored[positions[key]] = metric
            else:
                positions[key] = len(stored)
                stored.append(metric)
        manifest["updated_at"] = self._now()
        self._write_manifest(run_id, manifest)

    def record_timing(
        self,
        run_id: str,
        *,
        duration_seconds: float,
        target_minutes: int,
    ) -> None:
        """Persist the run duration and configured delivery target."""

        duration = max(0.0, float(duration_seconds))
        target = max(1, int(target_minutes))
        manifest = self.load_manifest(run_id)
        if manifest.get("timing"):
            return
        manifest["timing"] = {
            "duration_seconds": round(duration, 3),
            "target_minutes": target,
            "completed_within_target": (
                duration <= target * 60
            ),
        }
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
        if (
            not run_id
            or Path(run_id).name != run_id
            or "/" in run_id
            or "\\" in run_id
        ):
            raise ValueError("invalid FoodScope run ID")
        resolved_root = self.root.resolve()
        path = self.root / run_id
        if path.is_symlink():
            raise ValueError(
                "FoodScope run directory cannot be a symlink"
            )
        resolved_path = path.resolve()
        if resolved_path.parent != resolved_root:
            raise ValueError(
                "FoodScope run path escapes runs root"
            )
        if not resolved_path.is_dir():
            raise FileNotFoundError(f"unknown FoodScope run: {run_id}")
        return resolved_path

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
