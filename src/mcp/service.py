"""Application service for staged Horizon pipeline execution."""

from __future__ import annotations

import os
import re
import copy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import HorizonMcpError
from .horizon_adapter import (
    apply_source_filter,
    dicts_to_items,
    get_enabled_sources,
    get_source_counts,
    items_to_dicts,
    load_config,
    load_runtime,
    make_orchestrator,
    make_storage,
    resolve_config_path,
    resolve_horizon_path,
)
from .run_store import RunStore
from ..foodscope.loaders import (
    load_profile as load_foodscope_profile,
    load_source_packs as load_foodscope_source_packs,
)
from ..foodscope.run_store import (
    FoodRunStore,
    RunStage as FoodRunStage,
)
from ..foodscope.scheduler import (
    FoodScopeScheduler,
    resolve_run_window,
)
from ..services.webhook import WebhookNotifier


_REDACTED = "<redacted>"
_SENSITIVE_NAME = re.compile(
    r"(?:^|[-_])(authorization|cookie|credential|key|password|secret|signature|token|api[-_]?key)(?:$|[-_])",
    re.IGNORECASE,
)
_SENSITIVE_DIAGNOSTIC = re.compile(
    r"(?i)(authorization|cookie|credential|key|password|secret|signature|token)"
    r"\s*[:=]\s*[^\s,;]+"
)


def _redact_config(value: Any, key: str = "") -> Any:
    """Redact secrets from expanded config while preserving its structure."""
    if (
        key.lower() in {"error", "detail", "message"}
        and isinstance(value, str)
    ):
        return _sanitize_diagnostic(value)
    if key.lower().endswith("_env"):
        return value
    if _SENSITIVE_NAME.search(key):
        return _REDACTED
    if isinstance(value, dict):
        return {item_key: _redact_config(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    if not isinstance(value, str):
        return value

    lines = value.splitlines()
    if any(":" in line for line in lines):
        redacted_lines = []
        for line in lines:
            name, separator, header_value = line.partition(":")
            if separator and _SENSITIVE_NAME.search(name.strip()):
                line = f"{name}:{' ' if header_value.startswith(' ') else ''}{_REDACTED}"
            redacted_lines.append(line)
        value = "\n".join(redacted_lines)

    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"} and parts.netloc:
            netloc = parts.netloc
            if parts.username is not None or parts.password is not None:
                netloc = f"{_REDACTED}@{parts.hostname or ''}"
                if parts.port is not None:
                    netloc += f":{parts.port}"
            query = [
                (name, _REDACTED if _SENSITIVE_NAME.search(name) else item_value)
                for name, item_value in parse_qsl(parts.query, keep_blank_values=True)
            ]
            value = urlunsplit(parts._replace(netloc=netloc, query=urlencode(query)))
    except ValueError:
        pass
    return value


def _sanitize_diagnostic(value: Any) -> str:
    """Bound and redact free-form adapter/AI diagnostic text."""
    text = str(value)
    text = _SENSITIVE_DIAGNOSTIC.sub(
        lambda match: (
            f"{match.group(1)}=<redacted>"
        ),
        text,
    )
    return text[:500]


def _default_runs_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "mcp-runs"


def _get_fetch_report(orchestrator: Any) -> dict[str, Any] | None:
    """Return JSON-safe fetch diagnostics when supported by the runtime."""
    report = getattr(orchestrator, "last_fetch_report", None)
    if report is None:
        return None

    to_dict = getattr(report, "to_dict", None)
    if isinstance(report, dict):
        payload = report
    elif callable(to_dict):
        payload = to_dict()
    elif is_dataclass(report) and not isinstance(report, type):
        payload = asdict(cast(Any, report))
    else:
        payload = None
    return payload if isinstance(payload, dict) else None


@dataclass
class PipelineContext:
    """Resolved execution context per call."""

    horizon_path: Path
    config_path: Path
    runtime: Any
    config: Any


class HorizonPipelineService:
    """High-level staged pipeline service."""

    def __init__(
        self,
        runs_root: Path | None = None,
        foodscope_runs_root: Path | None = None,
    ):
        self.runs_root = Path(runs_root).resolve() if runs_root else _default_runs_root().resolve()
        self._run_store: RunStore | None = None
        default_foodscope_root = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "runs"
        )
        self.foodscope_runs_root = (
            Path(foodscope_runs_root).resolve()
            if foodscope_runs_root is not None
            else default_foodscope_root.resolve()
        )
        self._foodscope_run_store: FoodRunStore | None = None

    @property
    def run_store(self) -> RunStore:
        if self._run_store is None:
            self._run_store = RunStore(self.runs_root)
        return self._run_store

    @property
    def foodscope_run_store(self) -> FoodRunStore:
        if self._foodscope_run_store is None:
            self._foodscope_run_store = FoodRunStore(
                self.foodscope_runs_root
            )
        return self._foodscope_run_store

    def fs_list_runs(
        self, limit: int = 30
    ) -> dict[str, Any]:
        """List recent FoodScope runs without exposing source bodies."""
        if limit <= 0:
            raise HorizonMcpError(
                code="FS_INVALID_INPUT",
                message="limit must be greater than 0",
            )
        manifests: list[dict[str, Any]] = []
        root = self.foodscope_run_store.root
        for run_dir in root.iterdir():
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            try:
                manifest = self.foodscope_run_store.load_manifest(
                    run_dir.name
                )
            except (
                FileNotFoundError,
                ValueError,
                TypeError,
                OSError,
            ):
                continue
            manifests.append(
                {
                    "run_id": manifest.get(
                        "run_id", run_dir.name
                    ),
                    "profile_id": manifest.get("profile_id"),
                    "created_at": manifest.get("created_at"),
                    "updated_at": manifest.get("updated_at"),
                    "completed_stages": manifest.get(
                        "completed_stages", []
                    ),
                    "counts": manifest.get("counts", {}),
                    "facts_sha256": manifest.get(
                        "facts_sha256"
                    ),
                }
            )
        manifests.sort(
            key=lambda item: (
                item.get("updated_at")
                or item.get("created_at")
                or ""
            ),
            reverse=True,
        )
        return {
            "count": min(len(manifests), limit),
            "items": manifests[:limit],
            "truncated": len(manifests) > limit,
        }

    def fs_get_manifest(
        self, run_id: str
    ) -> dict[str, Any]:
        """Read one sanitized FoodScope run manifest."""
        try:
            manifest = self.foodscope_run_store.load_manifest(
                run_id
            )
        except ValueError as error:
            raise HorizonMcpError(
                code="FS_INVALID_RUN_ID",
                message="invalid FoodScope run ID",
                details={"run_id": run_id},
            ) from error
        except FileNotFoundError as error:
            raise HorizonMcpError(
                code="FS_RUN_NOT_FOUND",
                message="FoodScope run was not found",
                details={"run_id": run_id},
            ) from error
        return {
            "run_id": run_id,
            "manifest": _redact_config(manifest),
        }

    def fs_get_stage(
        self,
        run_id: str,
        stage: str,
        max_items: int = 200,
    ) -> dict[str, Any]:
        """Read a bounded FoodScope stage snapshot."""
        try:
            normalized_stage = FoodRunStage(stage)
        except ValueError as error:
            raise HorizonMcpError(
                code="FS_INVALID_STAGE",
                message="invalid FoodScope stage",
                details={
                    "stage": stage,
                    "allowed": [
                        value.value for value in FoodRunStage
                    ],
                },
            ) from error
        if max_items <= 0:
            raise HorizonMcpError(
                code="FS_INVALID_INPUT",
                message="max_items must be greater than 0",
            )
        bounded_limit = min(max_items, 500)
        try:
            payload = self.foodscope_run_store.load_stage(
                run_id, normalized_stage
            )
        except ValueError as error:
            if "run ID" in str(error):
                raise HorizonMcpError(
                    code="FS_INVALID_RUN_ID",
                    message="invalid FoodScope run ID",
                    details={"run_id": run_id},
                ) from error
            raise
        except FileNotFoundError as error:
            raise HorizonMcpError(
                code="FS_STAGE_NOT_FOUND",
                message="FoodScope stage was not found",
                details={
                    "run_id": run_id,
                    "stage": stage,
                },
            ) from error
        if isinstance(payload, list):
            serialized = [
                item.model_dump(mode="json")
                for item in payload
            ]
            return {
                "run_id": run_id,
                "stage": normalized_stage.value,
                "count": len(serialized),
                "items": serialized[:bounded_limit],
                "truncated": len(serialized) > bounded_limit,
            }
        return {
            "run_id": run_id,
            "stage": normalized_stage.value,
            "count": 1,
            "payload": payload,
            "truncated": False,
        }

    def fs_get_isolated(
        self,
        run_id: str,
        max_items: int = 200,
    ) -> dict[str, Any]:
        """Read bounded isolation diagnostics without article bodies."""
        if max_items <= 0:
            raise HorizonMcpError(
                code="FS_INVALID_INPUT",
                message="max_items must be greater than 0",
            )
        manifest = self.fs_get_manifest(run_id)["manifest"]
        isolation = manifest.get("isolation", [])
        safe_items = [
            {
                "item_id": str(entry.get("item_id", ""))[:200],
                "stage": str(entry.get("stage", ""))[:40],
                "error": _sanitize_diagnostic(
                    entry.get("error", "")
                ),
            }
            for entry in isolation
            if isinstance(entry, dict)
        ]
        bounded_limit = min(max_items, 500)
        return {
            "run_id": run_id,
            "count": len(safe_items),
            "items": safe_items[:bounded_limit],
            "truncated": len(safe_items) > bounded_limit,
        }

    def fs_get_brief(
        self, run_id: str, format: str
    ) -> dict[str, Any]:
        """Read canonical FoodScope facts, Markdown, or HTML."""
        if format not in {"facts", "markdown", "html"}:
            raise HorizonMcpError(
                code="FS_INVALID_FORMAT",
                message="invalid FoodScope brief format",
                details={
                    "format": format,
                    "allowed": [
                        "facts",
                        "markdown",
                        "html",
                    ],
                },
            )
        try:
            facts, rendered = (
                self.foodscope_run_store.load_brief_artifacts(
                    run_id
                )
            )
        except ValueError as error:
            if "run ID" in str(error):
                raise HorizonMcpError(
                    code="FS_INVALID_RUN_ID",
                    message="invalid FoodScope run ID",
                    details={"run_id": run_id},
                ) from error
            raise HorizonMcpError(
                code="FS_BRIEF_INVALID",
                message="stored FoodScope brief is invalid",
                details={"run_id": run_id},
            ) from error
        except (FileNotFoundError, KeyError) as error:
            raise HorizonMcpError(
                code="FS_BRIEF_NOT_FOUND",
                message="FoodScope brief was not found",
                details={"run_id": run_id},
            ) from error
        content: Any
        if format == "facts":
            content = facts.model_dump(mode="json")
        elif format == "markdown":
            content = rendered.markdown
        else:
            content = rendered.html
        return {
            "run_id": run_id,
            "format": format,
            "facts_sha256": rendered.facts_sha256,
            "content": content,
        }

    def fs_get_latest_brief(
        self, format: str
    ) -> dict[str, Any]:
        """Read the newest FoodScope brief."""
        run_id = self.foodscope_run_store.latest_run()
        if run_id is None:
            raise HorizonMcpError(
                code="FS_RUN_NOT_FOUND",
                message="no FoodScope run is available",
            )
        return self.fs_get_brief(run_id, format)

    async def fs_validate_config(
        self,
        *,
        horizon_path: str | None = None,
        config_path: str | None = None,
        check_env: bool = True,
    ) -> dict[str, Any]:
        """Validate FoodScope profiles, packs, schedule, and env names."""
        context = self._build_foodscope_context(
            horizon_path=horizon_path,
            config_path=config_path,
        )
        config = context.config
        try:
            profile = load_foodscope_profile(
                config.foodscope
            )
            sources = load_foodscope_source_packs(
                config.foodscope
            )
            FoodScopeScheduler(
                timezone=config.schedule.timezone,
                cron=config.schedule.cron,
            )
        except Exception as error:
            raise HorizonMcpError(
                code="FS_CONFIG_INVALID",
                message="FoodScope configuration is invalid",
                details={"error": str(error)},
            ) from error

        missing_env: list[str] = []
        if check_env:
            env_names = {
                config.ai_routes.fast.api_key_env,
                config.ai_routes.analysis.api_key_env,
            }
            if config.email and config.email.enabled:
                env_names.add(config.email.password_env)
            if config.webhook and config.webhook.enabled:
                if config.webhook.url_env:
                    env_names.add(config.webhook.url_env)
            if config.delivery.wechat.enabled:
                env_names.update(
                    {
                        config.delivery.wechat.app_id_env,
                        config.delivery.wechat.app_secret_env,
                    }
                )
            if (
                any(
                    source.enabled
                    and source.adapter == "x_official_api"
                    for source in sources
                )
                and config.foodscope.x_bearer_token_env
            ):
                env_names.add(
                    config.foodscope.x_bearer_token_env
                )
            missing_env = sorted(
                name
                for name in env_names
                if name and not os.getenv(name)
            )
        config_issues: list[str] = []
        if (
            config.delivery.wechat.enabled
            and not config.delivery.wechat.thumb_media_id
        ):
            config_issues.append(
                "delivery.wechat.thumb_media_id is required"
            )
        return {
            "valid": not missing_env and not config_issues,
            "profile": profile.model_dump(mode="json"),
            "source_count": len(sources),
            "source_pack_count": len(
                config.foodscope.source_packs
            ),
            "schedule": {
                "timezone": config.schedule.timezone,
                "cron": config.schedule.cron,
            },
            "missing_env": missing_env,
            "issues": config_issues,
        }

    async def fs_run_pipeline(
        self,
        *,
        hours: int | None = 30,
        since: str | None = None,
        until: str | None = None,
        profile: str | None = None,
        deliver: bool = False,
        resume_run_id: str | None = None,
        horizon_path: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        """Run FoodScope; external delivery is opt-in."""
        if profile is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]+", profile
        ):
            raise HorizonMcpError(
                code="FS_INVALID_PROFILE",
                message="invalid FoodScope profile ID",
            )
        if resume_run_id is not None:
            if (
                resume_run_id != "latest"
                and (
                    not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9._-]*",
                        resume_run_id,
                    )
                    or ".." in resume_run_id
                )
            ):
                raise HorizonMcpError(
                    code="FS_INVALID_RUN_ID",
                    message="invalid FoodScope run ID",
                )
            if since is not None or until is not None:
                raise HorizonMcpError(
                    code="FS_INVALID_WINDOW",
                    message=(
                        "resume_run_id cannot be combined "
                        "with since/until"
                    ),
                )
        if resume_run_id is None:
            try:
                resolve_run_window(
                    hours=(
                        None
                        if since is not None or until is not None
                        else hours
                    ),
                    since=since,
                    until=until,
                    lookback_hours=30,
                )
            except ValueError as error:
                raise HorizonMcpError(
                    code="FS_INVALID_WINDOW",
                    message=str(error),
                ) from error

        context = self._build_foodscope_context(
            horizon_path=horizon_path,
            config_path=config_path,
        )
        config = copy.deepcopy(context.config)
        if profile is not None:
            config.foodscope.profile = profile
            config.foodscope.profile_path = None
        storage = make_storage(
            context.runtime, context.config_path
        )
        orchestrator = make_orchestrator(
            context.runtime, config, storage
        )
        await orchestrator.run(
            force_hours=(
                None
                if since is not None or until is not None
                else hours
            ),
            since=since,
            until=until,
            deliver=deliver,
            resume_run_id=resume_run_id,
        )
        run_id = orchestrator.active_run_id
        if not run_id:
            raise HorizonMcpError(
                code="FS_RUN_FAILED",
                message="FoodScope did not create a run",
            )
        self._foodscope_run_store = orchestrator.run_store
        self.foodscope_runs_root = (
            orchestrator.run_store.root.resolve()
        )
        manifest = orchestrator.run_store.load_manifest(
            run_id
        )
        return {
            "run_id": run_id,
            "profile": config.foodscope.profile,
            "deliver": deliver,
            "facts_sha256": manifest.get(
                "facts_sha256"
            ),
            "completed_stages": manifest.get(
                "completed_stages", []
            ),
            "deliveries": manifest.get("deliveries", {}),
        }

    def list_runs(self, limit: int = 20) -> dict[str, Any]:
        """List recent runs and stage availability."""

        runs = self.run_store.list_runs(limit=limit)
        items = []
        for run in runs:
            run_id = run["run_id"]
            stages = {}
            for stage in ("raw", "scored", "filtered", "enriched"):
                stages[stage] = self.run_store.has_stage(run_id, stage)
            items.append(
                {
                    "run_id": run_id,
                    "created_at": run.get("created_at"),
                    "updated_at": run.get("updated_at"),
                    "stages": stages,
                    "meta": run.get("meta", {}),
                }
            )
        return {"count": len(items), "items": items}

    def get_run_meta(self, run_id: str) -> dict[str, Any]:
        """Read run metadata."""

        try:
            meta = self.run_store.load_meta(run_id)
        except FileNotFoundError as exc:
            raise HorizonMcpError(
                code="HZ_RUN_NOT_FOUND",
                message=f"run_id={run_id} does not exist.",
                details={"run_id": run_id},
            ) from exc
        return {"run_id": run_id, "meta": meta}

    def get_run_stage(
        self,
        run_id: str,
        stage: str,
        max_items: int = 200,
    ) -> dict[str, Any]:
        """Read staged item payload (JSON)."""

        if max_items <= 0:
            raise HorizonMcpError(code="HZ_INVALID_INPUT", message="max_items must be greater than 0.")
        try:
            items = self.run_store.load_items(run_id, stage)
        except ValueError as exc:
            raise HorizonMcpError(
                code="HZ_INVALID_STAGE",
                message=str(exc),
                details={"stage": stage},
            ) from exc
        except FileNotFoundError as exc:
            raise HorizonMcpError(
                code="HZ_STAGE_NOT_FOUND",
                message=f"run_id={run_id} is missing stage artifact: {stage}",
                details={"run_id": run_id, "stage": stage},
            ) from exc

        return {
            "run_id": run_id,
            "stage": stage,
            "count": len(items),
            "items": items[:max_items],
            "truncated": len(items) > max_items,
        }

    def get_run_summary(self, run_id: str, language: str = "zh") -> dict[str, Any]:
        """Read generated markdown summary for a run."""

        try:
            markdown = self.run_store.load_summary(run_id, language)
        except FileNotFoundError as exc:
            raise HorizonMcpError(
                code="HZ_SUMMARY_NOT_FOUND",
                message=f"run_id={run_id} is missing summary for language={language}.",
                details={"run_id": run_id, "language": language},
            ) from exc
        return {
            "run_id": run_id,
            "language": language,
            "summary": markdown,
        }

    def get_effective_config(
        self,
        horizon_path: str | None = None,
        config_path: str | None = None,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return effective config after optional source filtering."""

        ctx, selected_sources, unknown_sources = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=sources,
        )
        return {
            "horizon_path": str(ctx.horizon_path),
            "config_path": str(ctx.config_path),
            "selected_sources": selected_sources,
            "unknown_sources": unknown_sources,
            "config": _redact_config(ctx.config.model_dump(mode="json")),
        }

    async def validate_config(
        self,
        horizon_path: str | None = None,
        config_path: str | None = None,
        sources: list[str] | None = None,
        check_env: bool = True,
    ) -> dict[str, Any]:
        ctx, selected_sources, unknown_sources = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=sources,
        )

        warnings: list[str] = []
        missing_env: list[str] = []

        if check_env:
            required = [ctx.config.ai.api_key_env]
            for key in required:
                if not os.getenv(key):
                    missing_env.append(key)

            if ctx.config.sources.github and not os.getenv("GITHUB_TOKEN"):
                warnings.append("GITHUB_TOKEN is not set; GitHub fetching may hit strict rate limits.")

            if getattr(ctx.config, "email", None) and ctx.config.email and ctx.config.email.enabled:
                pwd_key = ctx.config.email.password_env
                if not os.getenv(pwd_key):
                    missing_env.append(pwd_key)

            if getattr(ctx.config, "webhook", None) and ctx.config.webhook and ctx.config.webhook.enabled:
                if ctx.config.webhook.url_env and not os.getenv(ctx.config.webhook.url_env):
                    missing_env.append(ctx.config.webhook.url_env)

        return {
            "horizon_path": str(ctx.horizon_path),
            "config_path": str(ctx.config_path),
            "ai": {
                "provider": ctx.config.ai.provider.value,
                "model": ctx.config.ai.model,
                "languages": list(ctx.config.ai.languages),
                "api_key_env": ctx.config.ai.api_key_env,
            },
            "filtering": {
                "ai_score_threshold": ctx.config.filtering.ai_score_threshold,
                "time_window_hours": ctx.config.filtering.time_window_hours,
                "max_items": ctx.config.filtering.max_items,
                "category_groups": {
                    key: group.model_dump(mode="json")
                    for key, group in ctx.config.filtering.category_groups.items()
                },
                "default_group": ctx.config.filtering.default_group,
                "default_group_limit": ctx.config.filtering.default_group_limit,
            },
            "enabled_sources": get_enabled_sources(ctx.config),
            "selected_sources": selected_sources,
            "unknown_sources": unknown_sources,
            "missing_env": missing_env,
            "warnings": warnings,
        }

    async def fetch_items(
        self,
        hours: int = 24,
        run_id: str | None = None,
        horizon_path: str | None = None,
        config_path: str | None = None,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        if hours <= 0:
            raise HorizonMcpError(code="HZ_INVALID_INPUT", message="hours must be greater than 0.")

        ctx, selected_sources, unknown_sources = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=sources,
        )

        storage = make_storage(ctx.runtime, ctx.config_path)
        orchestrator = make_orchestrator(ctx.runtime, ctx.config, storage)

        run_id = self.run_store.create_run(run_id)
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        raw_items = await orchestrator.fetch_all_sources(since)
        merged_items = orchestrator.merge_cross_source_duplicates(raw_items)
        fetch_report = _get_fetch_report(orchestrator)

        self.run_store.save_items(run_id, "raw", items_to_dicts(merged_items))
        meta_updates = {
            "horizon_path": str(ctx.horizon_path),
            "config_path": str(ctx.config_path),
            "hours": hours,
            "since": since.isoformat(),
            "source_selection": selected_sources,
            "unknown_sources": unknown_sources,
            "raw_count_before_merge": len(raw_items),
            "raw_count": len(merged_items),
        }
        if fetch_report is not None:
            meta_updates["fetch_status"] = fetch_report.get("status")
            meta_updates["fetch_report"] = fetch_report
        meta = self.run_store.update_meta(run_id, meta_updates)

        response = {
            "run_id": run_id,
            "fetched": len(merged_items),
            "raw_before_merge": len(raw_items),
            "source_counts": get_source_counts(merged_items),
            "artifact": str((self.run_store.run_dir(run_id) / "raw_items.json").resolve()),
            "meta": meta,
        }
        if fetch_report is not None:
            response["fetch_status"] = fetch_report.get("status")
            response["fetch_report"] = fetch_report
        return response

    async def score_items(
        self,
        run_id: str,
        source_stage: str = "raw",
        horizon_path: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        items, ctx = self._load_stage_items(
            run_id=run_id,
            stage=source_stage,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        if not items:
            raise HorizonMcpError(code="HZ_EMPTY_INPUT", message="No items available for scoring.")

        ai_client = ctx.runtime.create_ai_client(ctx.config.ai)
        analyzer = ctx.runtime.ContentAnalyzer(ai_client)
        scored_items = await analyzer.analyze_batch(items)

        self.run_store.save_items(run_id, "scored", items_to_dicts(scored_items))
        score_threshold = ctx.config.filtering.ai_score_threshold
        above_threshold = [x for x in scored_items if x.ai_score and x.ai_score >= score_threshold]

        meta = self.run_store.update_meta(
            run_id,
            {
                "scored_count": len(scored_items),
                "scored_threshold": score_threshold,
                "scored_above_threshold": len(above_threshold),
            },
        )

        return {
            "run_id": run_id,
            "scored": len(scored_items),
            "above_threshold": len(above_threshold),
            "score_distribution": self._score_distribution(scored_items),
            "artifact": str((self.run_store.run_dir(run_id) / "scored_items.json").resolve()),
            "meta": meta,
        }

    async def filter_items(
        self,
        run_id: str,
        threshold: float | None = None,
        source_stage: str = "scored",
        topic_dedup: bool = True,
        horizon_path: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        items, ctx = self._load_stage_items(
            run_id=run_id,
            stage=source_stage,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        effective_threshold = (
            threshold
            if threshold is not None
            else ctx.config.filtering.ai_score_threshold
        )
        storage = make_storage(ctx.runtime, ctx.config_path)
        orchestrator = make_orchestrator(ctx.runtime, ctx.config, storage)
        filtering_result = await orchestrator.filter_items(
            items,
            threshold=effective_threshold,
            topic_dedup=topic_dedup,
            log=False,
        )
        important_items = filtering_result.items
        balanced_result = filtering_result.balanced_digest
        balanced_enabled = balanced_result.enabled
        balanced_group_counts = balanced_result.group_counts

        self.run_store.save_items(run_id, "filtered", items_to_dicts(important_items))
        meta = self.run_store.update_meta(
            run_id,
            {
                "filtered_count": len(important_items),
                "filter_threshold": effective_threshold,
                "topic_dedup_enabled": topic_dedup,
                "topic_dedup_removed": filtering_result.topic_dedup_removed,
                "balanced_digest_enabled": balanced_enabled,
                "balanced_digest_group_counts": balanced_group_counts,
                "balanced_digest_removed": (
                    filtering_result.topic_dedup_count - len(important_items)
                ),
            },
        )

        return {
            "run_id": run_id,
            "kept": len(important_items),
            "threshold": effective_threshold,
            "removed_by_topic_dedup": filtering_result.topic_dedup_removed,
            "removed_by_balanced_digest": (
                filtering_result.topic_dedup_count - len(important_items)
            ),
            "balanced_digest_enabled": balanced_enabled,
            "group_counts": balanced_group_counts,
            "source_counts": get_source_counts(important_items),
            "artifact": str((self.run_store.run_dir(run_id) / "filtered_items.json").resolve()),
            "meta": meta,
        }

    async def enrich_items(
        self,
        run_id: str,
        source_stage: str = "filtered",
        horizon_path: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        items, ctx = self._load_stage_items(
            run_id=run_id,
            stage=source_stage,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        if not items:
            raise HorizonMcpError(code="HZ_EMPTY_INPUT", message="No items available for enrichment.")

        ai_client = ctx.runtime.create_ai_client(ctx.config.ai)
        enricher = ctx.runtime.ContentEnricher(ai_client)
        await enricher.enrich_batch(items)

        self.run_store.save_items(run_id, "enriched", items_to_dicts(items))

        citation_count = 0
        for item in items:
            citation_count += len(item.metadata.get("sources", []))

        meta = self.run_store.update_meta(
            run_id,
            {
                "enriched_count": len(items),
                "citation_count": citation_count,
            },
        )

        return {
            "run_id": run_id,
            "enriched": len(items),
            "citation_count": citation_count,
            "artifact": str((self.run_store.run_dir(run_id) / "enriched_items.json").resolve()),
            "meta": meta,
        }

    async def generate_summary(
        self,
        run_id: str,
        language: str = "zh",
        source_stage: str | None = None,
        horizon_path: str | None = None,
        config_path: str | None = None,
        save_to_horizon_data: bool = False,
    ) -> dict[str, Any]:
        stage = source_stage or self._pick_summary_stage(run_id)
        items, ctx = self._load_stage_items(
            run_id=run_id,
            stage=stage,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        total_fetched = self._total_fetched(run_id, fallback=len(items))
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        summarizer = ctx.runtime.DailySummarizer()
        summary = await summarizer.generate_summary(
            items,
            date_str,
            total_fetched,
            language=language,
        )

        run_summary_path = self.run_store.save_summary(run_id, language, summary)
        published_path = None
        if save_to_horizon_data:
            storage = make_storage(ctx.runtime, ctx.config_path)
            published_path = storage.save_daily_summary(date_str, summary, language=language)

        summary_meta = {
            "summary_stage": stage,
            "summary_language": language,
            "summary_generated_at": datetime.now(timezone.utc).isoformat(),
            "summary_artifact": str(run_summary_path.resolve()),
        }
        if published_path:
            summary_meta["summary_published_path"] = str(Path(published_path).resolve())
        meta = self.run_store.update_meta(run_id, summary_meta)

        return {
            "run_id": run_id,
            "language": language,
            "source_stage": stage,
            "total_fetched": total_fetched,
            "items_used": len(items),
            "summary_path": str(run_summary_path.resolve()),
            "published_path": str(Path(published_path).resolve()) if published_path else None,
            "preview": summary[:1200],
            "meta": meta,
        }

    async def run_pipeline(
        self,
        hours: int = 24,
        languages: list[str] | None = None,
        threshold: float | None = None,
        horizon_path: str | None = None,
        config_path: str | None = None,
        sources: list[str] | None = None,
        enrich: bool = True,
        topic_dedup: bool = True,
        save_to_horizon_data: bool = False,
    ) -> dict[str, Any]:
        fetch_result = await self.fetch_items(
            hours=hours,
            horizon_path=horizon_path,
            config_path=config_path,
            sources=sources,
        )
        run_id = fetch_result["run_id"]

        score_result = await self.score_items(
            run_id=run_id,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        filter_result = await self.filter_items(
            run_id=run_id,
            threshold=threshold,
            topic_dedup=topic_dedup,
            horizon_path=horizon_path,
            config_path=config_path,
        )

        enrich_result: dict[str, Any] | None = None
        stage_for_summary = "filtered"
        if enrich and filter_result["kept"] > 0:
            enrich_result = await self.enrich_items(
                run_id=run_id,
                source_stage="filtered",
                horizon_path=horizon_path,
                config_path=config_path,
            )
            stage_for_summary = "enriched"

        ctx, _, _ = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=sources,
        )
        final_languages = languages if languages else list(ctx.config.ai.languages)

        summaries = []
        for lang in final_languages:
            summary_result = await self.generate_summary(
                run_id=run_id,
                language=lang,
                source_stage=stage_for_summary,
                horizon_path=horizon_path,
                config_path=config_path,
                save_to_horizon_data=save_to_horizon_data,
            )
            summaries.append(summary_result)

        return {
            "run_id": run_id,
            "fetch": fetch_result,
            "score": score_result,
            "filter": filter_result,
            "enrich": enrich_result,
            "summaries": summaries,
            "meta": self.run_store.load_meta(run_id),
        }

    def _build_context(
        self,
        horizon_path: str | None,
        config_path: str | None,
        sources: list[str] | None,
    ) -> tuple[PipelineContext, list[str], list[str]]:
        resolved_horizon = resolve_horizon_path(horizon_path)
        runtime = load_runtime(resolved_horizon)
        resolved_config = resolve_config_path(resolved_horizon, config_path)
        config = load_config(runtime, resolved_config)
        effective_config, selected_sources, unknown_sources = apply_source_filter(config, sources)

        return (
            PipelineContext(
                horizon_path=resolved_horizon,
                config_path=resolved_config,
                runtime=runtime,
                config=effective_config,
            ),
            selected_sources,
            unknown_sources,
        )

    def _build_foodscope_context(
        self,
        *,
        horizon_path: str | None,
        config_path: str | None,
    ) -> PipelineContext:
        context, _, _ = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=None,
        )
        foodscope = getattr(
            context.config, "foodscope", None
        )
        if foodscope is None or not foodscope.enabled:
            raise HorizonMcpError(
                code="FS_NOT_ENABLED",
                message=(
                    "FoodScope MCP methods require "
                    "foodscope.enabled"
                ),
            )
        config = context.config.model_copy(deep=True)
        base = context.horizon_path
        fs_config = config.foodscope
        for field_name in (
            "source_pack_dir",
            "profile_dir",
        ):
            value = Path(getattr(fs_config, field_name))
            if not value.is_absolute():
                setattr(
                    fs_config,
                    field_name,
                    (base / value).resolve(),
                )
        if fs_config.profile_path is not None:
            profile_path = Path(fs_config.profile_path)
            if not profile_path.is_absolute():
                fs_config.profile_path = (
                    base / profile_path
                ).resolve()
        return PipelineContext(
            horizon_path=context.horizon_path,
            config_path=context.config_path,
            runtime=context.runtime,
            config=config,
        )

    def _load_stage_items(
        self,
        run_id: str,
        stage: str,
        horizon_path: str | None,
        config_path: str | None,
    ) -> tuple[list[Any], PipelineContext]:
        ctx, _, _ = self._build_context(horizon_path=horizon_path, config_path=config_path, sources=None)
        try:
            payload = self.run_store.load_items(run_id, stage)
        except FileNotFoundError as exc:
            raise HorizonMcpError(
                code="HZ_STAGE_NOT_FOUND",
                message=f"run_id={run_id} is missing stage artifact: {stage}",
                details={"run_id": run_id, "stage": stage},
            ) from exc
        items = dicts_to_items(ctx.runtime, payload)
        return items, ctx

    def _pick_summary_stage(self, run_id: str) -> str:
        for stage in ("enriched", "filtered", "scored", "raw"):
            if self.run_store.has_stage(run_id, stage):
                return stage
        raise HorizonMcpError(
            code="HZ_STAGE_NOT_FOUND",
            message=f"run_id={run_id} has no usable stage for summary generation.",
            details={"run_id": run_id},
        )

    def _total_fetched(self, run_id: str, fallback: int) -> int:
        try:
            raw = self.run_store.load_items(run_id, "raw")
            return len(raw)
        except Exception:
            return fallback

    @staticmethod
    def _score_distribution(items: list[Any]) -> dict[str, int]:
        buckets = {"0-2": 0, "3-4": 0, "5-6": 0, "7-8": 0, "9-10": 0}
        for item in items:
            score = float(item.ai_score or 0.0)
            if score < 3:
                buckets["0-2"] += 1
            elif score < 5:
                buckets["3-4"] += 1
            elif score < 7:
                buckets["5-6"] += 1
            elif score < 9:
                buckets["7-8"] += 1
            else:
                buckets["9-10"] += 1
        return buckets

    async def send_webhook(
        self,
        date: str,
        language: str = "zh",
        important_items: int = 0,
        all_items: int = 0,
        result: str = "success",
        summary: str = "",
        horizon_path: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        """Send a webhook notification using the configured webhook settings."""

        ctx, _, _ = self._build_context(
            horizon_path=horizon_path,
            config_path=config_path,
            sources=None,
        )

        webhook_config = ctx.config.webhook
        if not webhook_config:
            return {
                "sent": False,
                "status": "disabled",
                "reason": "Webhook is not configured.",
            }

        notifier = WebhookNotifier(webhook_config)
        variables = {
            "date": date,
            "language": language,
            "important_items": important_items,
            "all_items": all_items,
            "result": result,
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "message_title": f"Horizon {date} webhook",
            "message_kind": "manual",
            "summary": summary,
        }

        delivery = await notifier.notify(variables)

        return {
            **delivery.to_dict(),
            "variables": {
                key: (
                    value
                    if key != "summary"
                    else f"<{len(str(value))} chars>"
                )
                for key, value in variables.items()
            },
        }
