"""FoodScope orchestration integrated through Horizon's extension hooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import httpx

from src.ai.client import create_ai_client
from src.ai.tokens import TokenUsageSnapshot, get_usage_snapshot
from src.ai.summarizer import DailySummarizer
from src.error_utils import safe_error_detail
from src.models import Config, ContentItem
from src.orchestrator import (
    BalancedDigestResult,
    FilteringPipelineResult,
    FetchReport,
    HorizonOrchestrator,
    SourceFetchOutcome,
)
from src.storage.manager import StorageManager

from .analyzer import FoodContentAnalyzer
from .briefing import (
    BriefFacts,
    BriefMetadata,
    RenderedBrief,
    partition_brief_items,
)
from .config import EvidenceConfig
from .delivery import (
    DeliveryResult,
    DeliveryStatus,
    FoodDeliveryManager,
)
from .enricher import FoodContentEnricher
from .event_dedup import (
    FoodEventFingerprintStore,
    merge_food_events,
    merge_similar_food_events,
)
from .evidence import (
    EvidenceDecision,
    EvidencePolicy,
    summarize_evidence_decisions,
)
from .loaders import load_profile, load_source_packs
from .normalizer import normalize_item
from .rendering import FoodBriefRenderer
from .run_store import FoodRunStore, RunStage
from .scheduler import resolve_run_window
from .selector import FoodProfileSelector, SelectionResult
from .source_health import SourceRunMetric
from .sources.registry import (
    FoodSourceRegistry,
    order_fallback_sources,
    select_sources_for_run,
)
from .sources.original_url import OriginalUrlResolver
from .wechat import WeChatDraftClient


_COMMERCIAL_CATEGORIES = {
    "product_innovation",
    "ingredients_technology",
    "packaging_labeling",
    "consumer_trends",
    "retail_foodservice",
    "company_updates",
}


class FoodScopeOrchestrator(HorizonOrchestrator):
    """Food-industry workflow built on Horizon's parent run loop."""

    def __init__(self, config: Config, storage: StorageManager):
        super().__init__(config, storage)
        if config.foodscope is None or not config.foodscope.enabled:
            raise ValueError(
                "FoodScopeOrchestrator requires foodscope.enabled"
            )
        if config.ai_routes is None:
            raise ValueError(
                "FoodScopeOrchestrator requires ai_routes"
            )

        self.foodscope_config = config.foodscope
        self.profile = load_profile(self.foodscope_config)
        loaded_sources = load_source_packs(self.foodscope_config)
        self.source_specs_by_id = {
            source.id: source for source in loaded_sources
        }
        self.run_store = FoodRunStore(Path(storage.data_dir) / "runs")
        self.event_store = FoodEventFingerprintStore(
            Path(storage.data_dir)
            / "foodscope"
            / "event-fingerprints.json"
        )
        self.evidence_policy = EvidencePolicy(config.evidence)
        self.selector = FoodProfileSelector(self.evidence_policy)
        self.selection_result = SelectionResult(items=[])
        self.active_run_id: Optional[str] = None
        self._food_analyzer: FoodContentAnalyzer | None = None
        self._food_enricher: FoodContentEnricher | None = None
        self._brief_facts: BriefFacts | None = None
        self._rendered_brief: RenderedBrief | None = None
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None
        self._selected_source_ids: list[str] | None = None
        self._eligible_source_ids: list[str] | None = None
        self._skip_source_metric_update = False
        self.delivery_results: list[DeliveryResult] = []
        self._generic_webhook_delivered = False
        self._delivery_enabled = True
        self._token_usage_start: TokenUsageSnapshot | None = None
        self._run_started_at = 0.0
        self.wechat_draft_client = (
            WeChatDraftClient(self.config.delivery.wechat)
            if self.config.delivery.wechat.enabled
            else None
        )

    async def run(
        self,
        force_hours: int = None,
        *,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        deliver: bool = True,
        resume_run_id: str | None = None,
        run_provenance: Literal["manual", "scheduled"] = "manual",
    ) -> None:
        """Run or resume the FoodScope pipeline with an exact window."""
        self._brief_facts = None
        self._rendered_brief = None
        self.delivery_results = []
        self._generic_webhook_delivered = False
        self._delivery_enabled = deliver
        self._skip_source_metric_update = False
        self._token_usage_start = get_usage_snapshot()
        self._run_started_at = monotonic()
        resume_stage: RunStage | None = None

        if resume_run_id is not None:
            self.active_run_id, resume_stage = (
                self._prepare_resume(resume_run_id)
            )
            manifest = self.run_store.load_manifest(
                self.active_run_id
            )
            stored_selection = manifest.get("source_selection", [])
            self._selected_source_ids = [
                source_id
                for source_id in stored_selection
                if source_id in self.source_specs_by_id
            ]
            stored_eligible = manifest.get(
                "eligible_sources", []
            )
            self._eligible_source_ids = [
                source_id
                for source_id in stored_eligible
                if source_id in self.source_specs_by_id
            ]
            stored_source_hash = manifest.get(
                "source_config_sha256"
            )
            if (
                stored_source_hash is not None
                and stored_source_hash
                != self._source_config_sha256()
            ):
                raise ValueError(
                    "cannot resume a run after source "
                    "configuration changed"
                )
            self.last_fetch_report = (
                self._fetch_report_from_manifest(manifest)
            )
            self._skip_source_metric_update = (
                resume_stage == RunStage.SUMMARY
            )
            raw_window = manifest.get("run_window")
            if raw_window:
                self._window_start = datetime.fromisoformat(
                    raw_window["since"]
                )
                self._window_end = datetime.fromisoformat(
                    raw_window["until"]
                )
            else:
                window = resolve_run_window(
                    lookback_hours=(
                        self.config.collection.lookback_hours
                    )
                )
                self._window_start = window.since
                self._window_end = window.until
        else:
            window = resolve_run_window(
                hours=force_hours,
                since=since,
                until=until,
                lookback_hours=(
                    self.config.collection.lookback_hours
                ),
            )
            self._window_start = window.since
            self._window_end = window.until
            self.active_run_id = self.run_store.create_run(
                profile_id=self.profile.id,
                run_provenance=run_provenance,
                evidence_mode=self.evidence_policy.config.mode,
            )
            self.run_store.set_run_window(
                self.active_run_id,
                window.since,
                window.until,
            )
            selected_sources = select_sources_for_run(
                list(self.source_specs_by_id.values()),
                business_date=datetime.fromisoformat(
                    self._business_date(window.until)
                ).date(),
                minimum_sources=(
                    self.config.collection.minimum_sources_per_run
                ),
                extended_rotation_days=(
                    self.config.collection.extended_rotation_days
                ),
                discovery_rotation_days=(
                    self.config.collection.discovery_rotation_days
                ),
            )
            self._selected_source_ids = [
                source.id for source in selected_sources
            ]
            self._eligible_source_ids = [
                source.id
                for source in self.source_specs_by_id.values()
                if source.enabled
            ]
            self.run_store.set_source_selection(
                self.active_run_id,
                self._selected_source_ids,
                eligible_source_ids=self._eligible_source_ids,
                source_config_sha256=(
                    self._source_config_sha256()
                ),
            )

        try:
            await self._run_foodscope_pipeline(
                resume_stage=resume_stage,
                deliver=deliver,
            )
        except Exception as error:
            safe_error = safe_error_detail(
                error, "FoodScope generation failed"
            )
            self.console.print(
                f"[bold red]❌ Error: {safe_error}[/bold red]"
            )
            if (
                deliver
                and self.webhook_notifier is not None
            ):
                await self.webhook_notifier.send_failure(
                    date=self._business_date(
                        datetime.now(timezone.utc)
                    ),
                    error_message=safe_error,
                )
            raise
        finally:
            try:
                self._record_token_usage()
                if not self._skip_source_metric_update:
                    self._record_source_metrics()
            finally:
                if self.active_run_id is not None:
                    self.run_store.record_timing(
                        self.active_run_id,
                        duration_seconds=(
                            monotonic()
                            - self._run_started_at
                        ),
                        target_minutes=(
                            self.config.delivery.target_minutes
                        ),
                    )

    async def _run_foodscope_pipeline(
        self,
        *,
        resume_stage: RunStage | None,
        deliver: bool,
    ) -> None:
        if self.active_run_id is None:
            raise RuntimeError(
                "FoodScope run has not been created"
            )
        if (
            deliver
            and self.email_manager is not None
            and self.config.email is not None
            and self.config.email.enabled
            and self.config.email.imap_enabled
        ):
            self.email_manager.check_subscriptions(
                self.storage
            )

        stage_index = (
            list(RunStage).index(resume_stage)
            if resume_stage is not None
            else -1
        )
        if resume_stage == RunStage.SUMMARY:
            (
                self._brief_facts,
                self._rendered_brief,
            ) = self.run_store.load_brief_artifacts(
                self.active_run_id
            )
            if deliver:
                selected = self._selected_items_from_facts(
                    self._brief_facts
                )
                self.selection_result = self._selection_snapshot(
                    selected,
                    list(self._brief_facts.risk_alerts),
                )
                await self._deliver_summary(
                    summary=self._rendered_brief.markdown,
                    important_items=selected,
                    all_items_count=self._raw_count(),
                    date=self._brief_facts.metadata.date,
                    lang="zh",
                    summarizer=self._create_summarizer(),
                )
            return

        if stage_index >= list(RunStage).index(
            RunStage.RAW
        ):
            all_items = self._load_item_stage(RunStage.RAW)
        else:
            assert self._window_start is not None
            all_items = await self.fetch_all_sources(
                self._window_start, self._window_end
            )
            self._persist_source_outcomes()
            all_items = [
                item
                for item in all_items
                if self._item_in_window(item)
            ]
            await self._on_stage("raw", all_items)
            if (
                self.last_fetch_report is not None
                and self.last_fetch_report.all_failed
            ):
                raise RuntimeError(
                    self.last_fetch_report.failure_message()
                )
        if not all_items:
            self.console.print(
                "[yellow]No new content found. Exiting.[/yellow]"
            )
            return

        if stage_index >= list(RunStage).index(
            RunStage.NORMALIZED
        ):
            normalized_items = self._load_item_stage(
                RunStage.NORMALIZED
            )
        else:
            merged_items = self.merge_cross_source_duplicates(
                all_items
            )
            normalized_items = await self._normalize_items(
                merged_items
            )
            await self._on_stage(
                "normalized", normalized_items
            )

        if stage_index >= list(RunStage).index(
            RunStage.SCORED
        ):
            analyzed_items = self._load_item_stage(
                RunStage.SCORED
            )
        else:
            analyzed_items = await self._analyze_content(
                normalized_items
            )
            await self._on_stage("scored", analyzed_items)

        if stage_index >= list(RunStage).index(
            RunStage.FILTERED
        ):
            filtered_snapshot = self._load_item_stage(
                RunStage.FILTERED
            )
            important_items = self._restore_filtered_selection(
                filtered_snapshot
            )
            self.event_store.remember(filtered_snapshot)
        else:
            filtering_result = await self.filter_items(
                analyzed_items,
                apply_balance=False,
            )
            important_items = filtering_result.items
            await self._expand_twitter_discussion(
                important_items
            )
            important_items = self.apply_balanced_digest(
                important_items
            ).items
            await self._on_stage(
                "filtered", important_items
            )

        if stage_index >= list(RunStage).index(
            RunStage.ENRICHED
        ):
            enriched = self._load_item_stage(
                RunStage.ENRICHED
            )
            selected_ids = {
                item.id for item in important_items
            }
            enriched_by_id = {
                item.id: item for item in enriched
            }
            important_items = [
                enriched_by_id.get(item.id, item)
                for item in important_items
                if not enriched_by_id.get(
                    item.id, item
                ).metadata.get("foodscope_isolated")
            ]
            self.selection_result = SelectionResult(
                items=list(important_items),
                risk_alerts=[
                    item
                    for item in enriched
                    if item.id not in selected_ids
                    and not item.metadata.get("foodscope_isolated")
                ],
            )
        else:
            await self._enrich_important_items(
                important_items
            )
            await self._on_stage(
                "enriched", important_items
            )
            self._exclude_isolated_selection()
            important_items = list(self.selection_result.items)

        today = self._business_date(
            self._window_end or datetime.now(timezone.utc)
        )
        for language in self.config.ai.languages:
            summarizer = self._create_summarizer()
            summary = await self._generate_summary(
                important_items,
                today,
                self._raw_count(default=len(all_items)),
                language=language,
                summarizer=summarizer,
            )
            await self._on_stage(
                "summary",
                {
                    "language": language,
                    "date": today,
                    "total_fetched": self._raw_count(
                        default=len(all_items)
                    ),
                    "markdown": summary,
                },
            )
            self.storage.save_daily_summary(
                today, summary, language=language
            )
            await self._deliver_summary(
                summary=summary,
                important_items=important_items,
                all_items_count=self._raw_count(
                    default=len(all_items)
                ),
                date=today,
                lang=language,
                summarizer=summarizer,
            )

    def _prepare_resume(
        self, requested_run_id: str
    ) -> tuple[str, RunStage]:
        if requested_run_id == "latest":
            latest = self.run_store.latest_resumable_run()
            if latest is not None:
                run_id, stage = latest
                manifest = self.run_store.load_manifest(
                    run_id
                )
            else:
                latest_run_id = self.run_store.latest_run()
                if latest_run_id is None:
                    raise ValueError(
                        "no FoodScope run is available to resume"
                    )
                run_id = latest_run_id
                manifest = self.run_store.load_manifest(
                    run_id
                )
                completed = manifest.get(
                    "completed_stages", []
                )
                if not completed:
                    raise ValueError(
                        "latest FoodScope run has no completed stage"
                    )
                stage = RunStage(completed[-1])
        else:
            run_id = requested_run_id
            manifest = self.run_store.load_manifest(run_id)
            completed = manifest.get(
                "completed_stages", []
            )
            if not completed:
                raise ValueError(
                    "FoodScope run has no completed stage"
                )
            stage = max(
                (RunStage(value) for value in completed),
                key=lambda value: list(RunStage).index(value),
            )
        if manifest.get("profile_id") != self.profile.id:
            raise ValueError(
                "cannot resume a run created with a different profile"
            )
        if (
            manifest.get("schema_version")
            != self.run_store.SCHEMA_VERSION
        ):
            raise ValueError(
                "cannot resume a run with a different schema version"
            )
        required = {
            stage.value
            for stage in list(RunStage)[
                : list(RunStage).index(stage) + 1
            ]
        }
        if not required.issubset(
            set(manifest.get("completed_stages", []))
        ):
            raise ValueError(
                "cannot resume a run with non-contiguous stages"
            )
        return run_id, stage

    def _load_item_stage(
        self, stage: RunStage
    ) -> list[ContentItem]:
        if self.active_run_id is None:
            raise RuntimeError(
                "FoodScope run has not been created"
            )
        payload = self.run_store.load_stage(
            self.active_run_id, stage
        )
        if not isinstance(payload, list):
            raise ValueError(
                f"{stage.value} stage is not an item list"
            )
        return payload

    def _raw_count(self, *, default: int = 0) -> int:
        if self.active_run_id is None:
            return default
        manifest = self.run_store.load_manifest(
            self.active_run_id
        )
        return int(
            manifest.get("counts", {}).get("raw", default)
        )

    def _item_in_window(self, item: ContentItem) -> bool:
        if (
            self._window_start is None
            or self._window_end is None
        ):
            return True
        published_at = item.published_at
        if (
            published_at.tzinfo is None
            or published_at.utcoffset() is None
        ):
            return False
        return (
            self._window_start.astimezone(timezone.utc)
            <= published_at.astimezone(timezone.utc)
            <= self._window_end.astimezone(timezone.utc)
        )

    async def fetch_all_sources(
        self,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        """Fetch legacy and FoodScope pack sources independently."""
        parent_items = await super().fetch_all_sources(
            since, until
        )
        parent_outcomes = (
            list(self.last_fetch_report.outcomes)
            if self.last_fetch_report is not None
            else []
        )
        selected_ids = getattr(
            self, "_selected_source_ids", None
        )
        food_items: list[ContentItem] = []
        food_outcomes: list[SourceFetchOutcome] = []

        def selected_sources() -> list:
            current_selected_ids = getattr(
                self, "_selected_source_ids", selected_ids
            )
            return [
                source
                for source_id, source in self.source_specs_by_id.items()
                if (
                    current_selected_ids is None
                    or source_id in current_selected_ids
                )
            ]

        if selected_sources():
            async with httpx.AsyncClient(timeout=30.0) as client:
                registry = FoodSourceRegistry(client)

                async def fetch_food_window(
                    window_since: datetime,
                ) -> tuple[
                    list[ContentItem],
                    list[SourceFetchOutcome],
                ]:
                    current_sources = selected_sources()
                    items, outcomes = await registry.fetch(
                        current_sources, window_since, until
                    )
                    active_run_id = getattr(
                        self, "active_run_id", None
                    )
                    fallback_limit = (
                        self.config.collection.fallback_sources_per_run
                        if (
                            selected_ids is not None
                            and active_run_id is not None
                        )
                        else 0
                    )
                    shortage = sum(
                        outcome.status in {"empty", "failure"}
                        for outcome in outcomes
                    )
                    if fallback_limit and shortage:
                        eligible_ids = set(
                            self._eligible_source_ids
                            or (
                                source.id
                                for source
                                in self.source_specs_by_id.values()
                                if source.enabled
                            )
                        )
                        already_selected_ids = list(
                            (
                                getattr(
                                    self,
                                    "_selected_source_ids",
                                    selected_ids or [],
                                )
                                or []
                            )
                        )
                        already_selected = set(already_selected_ids)
                        deferred = [
                            source
                            for source
                            in self.source_specs_by_id.values()
                            if source.id in eligible_ids
                            and source.id not in already_selected
                        ]
                        business_date = datetime.fromisoformat(
                            self._business_date(
                                until
                                or self._window_end
                                or datetime.now(timezone.utc)
                            )
                        ).date()
                        fallback_sources = order_fallback_sources(
                            deferred,
                            business_date=business_date,
                        )[: min(shortage, fallback_limit)]
                        if fallback_sources:
                            assert isinstance(active_run_id, str)
                            (
                                fallback_items,
                                fallback_outcomes,
                            ) = await registry.fetch(
                                fallback_sources, window_since, until
                            )
                            items.extend(fallback_items)
                            outcomes.extend(fallback_outcomes)
                            self._selected_source_ids = [
                                *already_selected_ids,
                                *(
                                    source.id
                                    for source in fallback_sources
                                ),
                            ]
                            self.run_store.set_source_selection(
                                active_run_id,
                                self._selected_source_ids,
                                eligible_source_ids=(
                                    self._eligible_source_ids
                                ),
                                source_config_sha256=(
                                    self._source_config_sha256()
                                ),
                            )
                    return items, outcomes

                food_items, food_outcomes = await fetch_food_window(
                    since
                )
                raw_config = getattr(self, "config", None)
                collection = getattr(raw_config, "collection", None)
                if getattr(
                    collection,
                    "adaptive_lookback_enabled",
                    False,
                ):
                    window_end = (
                        until
                        or self._window_end
                        or datetime.now(timezone.utc)
                    )
                    current_since = since.astimezone(timezone.utc)
                    outcome_positions = {
                        outcome.source_name: index
                        for index, outcome in enumerate(food_outcomes)
                    }
                    retry_ids = {
                        outcome.source_name
                        for outcome in food_outcomes
                        if (
                            outcome.status == "empty"
                            and (
                                source := self.source_specs_by_id.get(
                                    outcome.source_name
                                )
                            )
                            is not None
                            and source.adapter != "discovery_query"
                        )
                    }
                    for hours in getattr(
                        collection,
                        "adaptive_lookback_hours",
                        [],
                    ):
                        if not retry_ids:
                            break
                        expanded_since = window_end - timedelta(
                            hours=hours
                        )
                        if (
                            expanded_since.astimezone(timezone.utc)
                            >= current_since
                        ):
                            continue
                        retry_sources = [
                            source
                            for source_id, source
                            in self.source_specs_by_id.items()
                            if source_id in retry_ids
                        ]
                        (
                            expanded_items,
                            expanded_outcomes,
                        ) = await registry.fetch(
                            retry_sources,
                            expanded_since,
                            until,
                        )
                        food_items.extend(expanded_items)
                        retry_ids = set()
                        for outcome in expanded_outcomes:
                            position = outcome_positions.get(
                                outcome.source_name
                            )
                            if position is None:
                                outcome_positions[
                                    outcome.source_name
                                ] = len(food_outcomes)
                                food_outcomes.append(outcome)
                            else:
                                food_outcomes[position] = outcome
                            if outcome.status == "empty":
                                retry_ids.add(outcome.source_name)
                evidence_config = getattr(
                    getattr(self, "config", None),
                    "evidence",
                    EvidenceConfig(),
                )
                await OriginalUrlResolver(
                    client,
                    enabled=evidence_config.resolve_original_urls,
                ).resolve_items(
                    food_items,
                    allow_aggregator_fallback=(
                        evidence_config.allow_aggregator_fallback
                    ),
                )
        self.last_fetch_report = FetchReport(
            outcomes=parent_outcomes + food_outcomes
        )
        return parent_items + food_items

    def _persist_source_outcomes(self) -> None:
        if (
            self.active_run_id is None
            or self.last_fetch_report is None
        ):
            return
        self.run_store.record_source_outcomes(
            self.active_run_id,
            [
                {
                    **outcome.to_dict(),
                    "candidate_count": (
                        outcome.candidate_count
                        if outcome.candidate_count is not None
                        else len(outcome.items)
                    ),
                }
                for outcome in self.last_fetch_report.outcomes
            ],
        )

    @staticmethod
    def _fetch_report_from_manifest(
        manifest: dict,
    ) -> FetchReport | None:
        outcomes: list[SourceFetchOutcome] = []
        for row in manifest.get("source_outcomes", []):
            status = row.get("status")
            source_name = row.get("source")
            if (
                status not in {"success", "empty", "failure"}
                or not isinstance(source_name, str)
            ):
                continue
            outcomes.append(
                SourceFetchOutcome(
                    source_name=source_name,
                    status=status,
                    error=row.get("error"),
                    candidate_count=row.get("candidate_count"),
                    published_at_candidate_count=row.get(
                        "published_at_candidate_count"
                    ),
                    published_at_parse_count=row.get(
                        "published_at_parse_count"
                    ),
                    window_since=row.get("window_since"),
                    window_until=row.get("window_until"),
                )
            )
        return FetchReport(outcomes) if outcomes else None

    def _determine_time_window(
        self, force_hours: int = None
    ) -> datetime:
        self._window_end = datetime.now(timezone.utc)
        hours = (
            force_hours
            if force_hours is not None
            else self.config.collection.lookback_hours
        )
        self._window_start = self._window_end - timedelta(hours=hours)
        return self._window_start

    async def _normalize_items(
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        for item in items:
            if item.food is not None:
                continue
            raw_source_id = item.metadata.get("food_source_id")
            source_id = (
                raw_source_id
                if isinstance(raw_source_id, str)
                else ""
            )
            source = self.source_specs_by_id.get(source_id)
            if source is None:
                item.ai_score = 0.0
                item.ai_reason = "Unknown FoodScope source contract"
                item.metadata.update(
                    {
                        "foodscope_isolated": True,
                        "foodscope_isolation_stage": "normalized",
                        "foodscope_analysis_error": (
                            "missing FoodScope source contract"
                        ),
                    }
                )
                continue
            normalize_item(item, source)
        return items

    async def _on_stage(self, stage: str, payload: object) -> None:
        if self.active_run_id is None:
            raise RuntimeError("FoodScope run has not been created")
        run_stage = RunStage(stage)
        stored_payload: list[ContentItem] | dict | str
        if (
            run_stage != RunStage.SUMMARY
            and isinstance(payload, list)
            and all(
                isinstance(item, ContentItem) for item in payload
            )
        ):
            stored_payload = payload
        elif isinstance(payload, (dict, str)):
            stored_payload = payload
        else:
            raise TypeError(
                f"invalid payload for {run_stage.value} stage"
            )
        if run_stage == RunStage.ENRICHED and isinstance(payload, list):
            stored_payload = self._with_risk_alerts(payload)
        elif run_stage == RunStage.FILTERED and isinstance(payload, list):
            stored_payload = self._with_risk_alerts(
                payload, mark_risk_alerts=True
            )
        elif (
            run_stage == RunStage.SUMMARY
            and isinstance(payload, dict)
            and self._rendered_brief is not None
        ):
            stored_payload = {
                **payload,
                "facts_sha256": self._rendered_brief.facts_sha256,
            }
        self.run_store.save_stage(
            self.active_run_id, run_stage, stored_payload
        )
        if run_stage == RunStage.FILTERED:
            assert isinstance(stored_payload, list)
            self.event_store.remember(stored_payload)

    async def _analyze_content(
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        ready = [
            item
            for item in items
            if item.food is not None
            and not item.metadata.get("foodscope_isolated")
        ]
        if ready:
            await self._get_food_analyzer().analyze_batch(ready)
        return items

    async def filter_items(
        self,
        items: list[ContentItem],
        *,
        threshold: Optional[float] = None,
        topic_dedup: bool = True,
        apply_balance: bool = True,
        log: bool = True,
    ) -> FilteringPipelineResult:
        """Merge industry events and admit them through evidence rules."""
        merged = merge_food_events(items)
        if topic_dedup:
            merged = merge_similar_food_events(merged)
        admitted: list[ContentItem] = []
        decisions: list[EvidenceDecision] = []
        for item in merged:
            decision = self.evidence_policy.evaluate(item)
            decisions.append(decision)
            item.metadata["foodscope_admission_mode"] = (
                self.evidence_policy.config.mode
            )
            item.metadata["foodscope_admission_reason"] = (
                decision.reason
            )
            if decision.accepted:
                admitted.append(item)
                continue
            item.metadata["foodscope_evidence_rejected"] = True
            item.metadata["foodscope_evidence_reason"] = decision.reason
            if (
                self.active_run_id is not None
                and not item.metadata.get("foodscope_isolated")
            ):
                self.run_store.record_isolation(
                    self.active_run_id,
                    item_id=item.id,
                    stage=RunStage.FILTERED,
                    error=f"evidence rejected: {decision.reason}",
                )
        admission_summary = summarize_evidence_decisions(
            self.evidence_policy.config.mode,
            decisions,
        )
        if self.active_run_id is not None:
            self.run_store.record_evidence_admission(
                self.active_run_id,
                admission_summary,
            )
        if log:
            accepted = sum(
                int(value)
                for key, value in admission_summary.items()
                if key.startswith("accepted_")
            )
            rejected = len(decisions) - accepted
            reason_counts = "; ".join(
                f"{key}={value}"
                for key, value in admission_summary.items()
                if key != "mode"
            )
            self.console.print(
                "[dim]Evidence admission: "
                f"mode={admission_summary['mode']}; "
                f"accepted={accepted}; rejected={rejected}; "
                f"{reason_counts}[/dim]"
            )

        balanced = (
            self.apply_balanced_digest(admitted, log=log)
            if apply_balance
            else BalancedDigestResult(items=admitted)
        )
        return FilteringPipelineResult(
            items=balanced.items,
            threshold_count=len(admitted),
            topic_dedup_count=len(merged),
            topic_dedup_removed=len(items) - len(merged),
            balanced_digest=balanced,
        )

    def apply_balanced_digest(
        self,
        items: list[ContentItem],
        *,
        log: bool = True,
    ) -> BalancedDigestResult:
        """Apply event memory and the active FoodScope profile."""
        new_items = self.event_store.filter_new(items)
        self.selection_result = self.selector.select(
            new_items, self.profile
        )
        return BalancedDigestResult(
            items=self.selection_result.items,
            enabled=True,
            group_counts=self.selection_result.category_counts,
        )

    async def _enrich_important_items(
        self, items: list[ContentItem]
    ) -> None:
        enrichment_items = self._with_risk_alerts(items)
        if enrichment_items:
            await self._get_food_enricher().enrich(enrichment_items)

    async def _generate_summary(
        self,
        items: list[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "zh",
        summarizer: Optional[DailySummarizer] = None,
    ) -> str:
        """Render and persist one canonical FoodScope fact snapshot."""
        if self._rendered_brief is not None:
            return self._rendered_brief.markdown
        if self.active_run_id is None:
            raise RuntimeError("FoodScope run has not been created")

        selected = [
            self._ordered_copy(item, index)
            for index, item in enumerate(items)
        ]
        risk_alerts = [
            self._ordered_copy(item, index)
            for index, item in enumerate(
                self.selection_result.risk_alerts
            )
        ]
        must_read, news = partition_brief_items(
            selected, risk_alerts
        )
        manifest = self.run_store.load_manifest(
            self.active_run_id
        )
        source_outcomes = (
            self.last_fetch_report.outcomes
            if self.last_fetch_report is not None
            else []
        )
        generated_at = datetime.now(timezone.utc)
        window_end = self._window_end or generated_at
        window_start = self._window_start or (
            window_end
            - timedelta(hours=self.config.collection.lookback_hours)
        )
        self._brief_facts = BriefFacts(
            metadata=BriefMetadata(
                run_id=self.active_run_id,
                profile_id=self.profile.id,
                profile_name=self.profile.name,
                date=date,
                window_start=window_start,
                window_end=window_end,
                generated_at=generated_at,
                fetched_count=total_fetched,
                candidate_count=manifest.get("counts", {}).get(
                    "scored", total_fetched
                ),
                selected_count=len(selected) + len(risk_alerts),
                isolated_count=len(
                    manifest.get("isolation", [])
                ),
                source_success_count=sum(
                    outcome.status in {"success", "empty"}
                    for outcome in source_outcomes
                ),
                source_failure_count=sum(
                    outcome.status == "failure"
                    for outcome in source_outcomes
                ),
            ),
            risk_alerts=[],
            must_read=must_read,
            news=news,
            sections={},
            observations=[],
        )
        self._rendered_brief = FoodBriefRenderer().render(
            self._brief_facts
        )
        self.run_store.save_brief_artifacts(
            self.active_run_id,
            self._brief_facts,
            self._rendered_brief,
        )
        return self._rendered_brief.markdown

    async def _deliver_summary(
        self,
        summary: str,
        important_items: list[ContentItem],
        all_items_count: int,
        date: str,
        lang: str,
        summarizer: DailySummarizer,
    ) -> None:
        """Deliver the saved canonical brief through isolated adapters."""
        if (
            self.active_run_id is None
            or self._brief_facts is None
            or self._rendered_brief is None
        ):
            raise RuntimeError(
                "FoodScope brief artifacts are not ready"
            )
        manager = FoodDeliveryManager(
            run_id=self.active_run_id,
            run_store=self.run_store,
            config=self.config.delivery,
            email_manager=(
                self.email_manager
                if self._delivery_enabled
                else None
            ),
            subscribers=(
                self.storage.load_subscribers()
                if self._delivery_enabled
                else []
            ),
            webhook_notifier=(
                self.webhook_notifier
                if self._delivery_enabled
                else None
            ),
            wechat_client=(
                self.wechat_draft_client
                if self._delivery_enabled
                else None
            ),
        )
        self.delivery_results = await manager.deliver(
            self._brief_facts, self._rendered_brief
        )

        # A non-Feishu Horizon webhook retains its established Markdown
        # template substitution. It is intentionally separate from the
        # structured Feishu Card JSON 2.0 channel.
        webhook_config = getattr(
            self.webhook_notifier, "config", None
        )
        platform = str(
            getattr(webhook_config, "platform", "")
        ).lower()
        if (
            self.webhook_notifier is not None
            and self._delivery_enabled
            and platform not in {"feishu", "lark"}
            and not self._generic_webhook_delivered
        ):
            messages = (
                self.webhook_notifier.build_daily_summary_messages(
                summary=self._rendered_brief.markdown,
                important_items=important_items,
                all_items_count=all_items_count,
                date=date,
                lang=lang,
                summarizer=summarizer,
                )
            )
            webhook_result = await manager.deliver_generic_webhook(
                messages,
                self._rendered_brief.facts_sha256,
            )
            self.delivery_results.append(webhook_result)
            self._generic_webhook_delivered = (
                webhook_result.status
                in {
                    DeliveryStatus.SUCCESS,
                    DeliveryStatus.SKIPPED,
                }
            )

    def _get_food_analyzer(self) -> FoodContentAnalyzer:
        if self._food_analyzer is None:
            assert self.config.ai_routes is not None
            route = self.config.ai_routes.fast
            self._food_analyzer = FoodContentAnalyzer(
                create_ai_client(route),
                profile_id=self.profile.id,
                max_attempts=route.max_attempts,
                concurrency=route.concurrency,
                timeout_seconds=route.timeout_seconds,
            )
        return self._food_analyzer

    def _get_food_enricher(self) -> FoodContentEnricher:
        if self._food_enricher is None:
            assert self.config.ai_routes is not None
            route = self.config.ai_routes.analysis
            self._food_enricher = FoodContentEnricher(
                create_ai_client(route),
                max_attempts=route.max_attempts,
                concurrency=route.concurrency,
                timeout_seconds=route.timeout_seconds,
            )
        return self._food_enricher

    def _with_risk_alerts(
        self,
        items: list[ContentItem],
        *,
        mark_risk_alerts: bool = False,
    ) -> list[ContentItem]:
        combined = list(items)
        if mark_risk_alerts:
            for item in combined:
                item.metadata.pop("foodscope_risk_alert", None)
        item_ids = {item.id for item in combined}
        for alert in self.selection_result.risk_alerts:
            if mark_risk_alerts:
                alert.metadata["foodscope_risk_alert"] = True
            if alert.id not in item_ids:
                combined.append(alert)
                item_ids.add(alert.id)
        return combined

    def _restore_filtered_selection(
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        risk_alerts = [
            item
            for item in items
            if item.metadata.get("foodscope_risk_alert") is True
        ]
        regular = [
            item
            for item in items
            if item.metadata.get("foodscope_risk_alert") is not True
        ]
        self.selection_result = self._selection_snapshot(
            regular, risk_alerts
        )
        return regular

    def _exclude_isolated_selection(self) -> None:
        self.selection_result = self._selection_snapshot(
            [
                item
                for item in self.selection_result.items
                if not item.metadata.get("foodscope_isolated")
            ],
            [
                item
                for item in self.selection_result.risk_alerts
                if not item.metadata.get("foodscope_isolated")
            ],
        )

    @staticmethod
    def _selected_items_from_facts(
        facts: BriefFacts,
    ) -> list[ContentItem]:
        by_id: dict[str, ContentItem] = {}
        for item in (
            facts.risk_alerts
            + facts.must_read
            + facts.news
        ):
            by_id.setdefault(item.id, item)
        for items in facts.sections.values():
            for item in items:
                by_id.setdefault(item.id, item)

        def selection_order(item: ContentItem) -> int:
            raw = item.metadata.get("selection_order", 0)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0

        return sorted(
            by_id.values(),
            key=selection_order,
        )

    @staticmethod
    def _selection_snapshot(
        items: list[ContentItem],
        risk_alerts: list[ContentItem],
    ) -> SelectionResult:
        category_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for item in items:
            if item.food is None:
                continue
            category = item.food.category.value
            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )
            source_counts[item.food.source_id] = (
                source_counts.get(item.food.source_id, 0) + 1
            )
        return SelectionResult(
            items=list(items),
            risk_alerts=list(risk_alerts),
            category_counts=category_counts,
            source_counts=source_counts,
        )

    def _record_token_usage(self) -> None:
        if (
            self.active_run_id is None
            or self._token_usage_start is None
        ):
            return
        current = get_usage_snapshot()
        baseline = self._token_usage_start
        per_model: list[dict] = []
        for key, usage in sorted(current.per_model.items()):
            prior = baseline.per_model.get(key)
            input_tokens = max(
                0,
                usage.input_tokens
                - (prior.input_tokens if prior else 0),
            )
            output_tokens = max(
                0,
                usage.output_tokens
                - (prior.output_tokens if prior else 0),
            )
            if input_tokens + output_tokens == 0:
                continue
            provider, _, model = key.partition("/")
            per_model.append(
                {
                    "key": key,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            )
        pricing = []
        assert self.config.ai_routes is not None
        for route_name, route in (
            ("fast", self.config.ai_routes.fast),
            ("analysis", self.config.ai_routes.analysis),
        ):
            pricing.append(
                {
                    "route": route_name,
                    "provider": route.provider.value,
                    "model": route.model,
                    "input_cost_per_million": (
                        route.input_cost_per_million
                    ),
                    "output_cost_per_million": (
                        route.output_cost_per_million
                    ),
                }
            )
        self.run_store.record_token_usage(
            self.active_run_id,
            input_tokens=max(
                0,
                current.total_input_tokens
                - baseline.total_input_tokens,
            ),
            output_tokens=max(
                0,
                current.total_output_tokens
                - baseline.total_output_tokens,
            ),
            per_model=per_model,
            pricing=pricing,
        )

    def _record_source_metrics(self) -> None:
        if (
            self.active_run_id is None
            or self.last_fetch_report is None
        ):
            return
        manifest = self.run_store.load_manifest(
            self.active_run_id
        )
        run_provenance = manifest.get(
            "run_provenance", "manual"
        )
        outcomes = {
            outcome.source_name: outcome
            for outcome in self.last_fetch_report.outcomes
            if outcome.source_name in self.source_specs_by_id
        }
        source_ids = (
            sorted(
                source_id
                for source_id in (
                    self._eligible_source_ids
                    if self._eligible_source_ids is not None
                    else [
                        source.id
                        for source
                        in self.source_specs_by_id.values()
                        if source.enabled
                    ]
                )
                if source_id in self.source_specs_by_id
            )
            if run_provenance == "scheduled"
            else sorted(outcomes)
        )
        if not source_ids:
            return
        try:
            scored = self.run_store.load_stage(
                self.active_run_id, RunStage.SCORED
            )
        except FileNotFoundError:
            scored = []
        if not isinstance(scored, list):
            scored = []
        admitted = (
            self.selection_result.items
            + self.selection_result.risk_alerts
        )
        total_candidates = sum(
            (
                outcome.candidate_count
                if outcome.candidate_count is not None
                else len(outcome.items)
            )
            for outcome in outcomes.values()
        )
        token_usage = manifest.get("token_usage") or {}
        run_tokens = int(token_usage.get("total_tokens", 0))
        run_cost = token_usage.get("estimated_cost")
        metrics: list[dict] = []
        for source_id in source_ids:
            outcome = outcomes.get(source_id)
            source = self.source_specs_by_id[source_id]
            source_scored = [
                item
                for item in scored
                if item.food is not None
                and item.food.source_id == source_id
            ]
            relevant = [
                item
                for item in source_scored
                if not item.metadata.get("foodscope_isolated")
                and item.metadata.get("foodscope_relevant")
                is not False
            ]
            source_admitted = [
                item
                for item in admitted
                if item.food is not None
                and item.food.source_id == source_id
            ]
            event_keys = {
                item.food.event_key or item.id
                for item in source_admitted
                if item.food is not None
            }
            duplicate_count = sum(
                max(
                    0,
                    len(item.metadata.get("event_sources", []))
                    - 1,
                )
                for item in source_admitted
            )
            candidate_count = (
                0
                if outcome is None
                else (
                    outcome.candidate_count
                    if outcome.candidate_count is not None
                    else len(outcome.items)
                )
            )
            allocated_tokens = (
                round(
                    run_tokens
                    * candidate_count
                    / total_candidates
                )
                if outcome is not None and total_candidates
                else 0
            )
            allocated_cost = (
                float(run_cost)
                * candidate_count
                / total_candidates
                if (
                    outcome is not None
                    and run_cost is not None
                    and total_candidates
                )
                else (
                    0.0 if outcome is None else None
                )
            )
            metric = SourceRunMetric(
                source_id=source_id,
                run_id=self.active_run_id,
                observed_date=datetime.fromisoformat(
                    self._business_date(
                        self._window_end
                        or datetime.now(timezone.utc)
                    )
                ).date(),
                run_provenance=run_provenance,
                fetch_status=(
                    outcome.status
                    if outcome is not None
                    else "skipped_rotation"
                ),
                published_at_parse_rate=(
                    self._parse_rate(outcome)
                    if outcome is not None
                    else 0.0
                ),
                candidate_count=candidate_count,
                food_relevant_count=len(relevant),
                admitted_count=len(source_admitted),
                commercial_count=sum(
                    item.food is not None
                    and item.food.category.value
                    in _COMMERCIAL_CATEGORIES
                    for item in source_admitted
                ),
                duplicate_event_count=duplicate_count,
                unique_event_count=len(event_keys),
                sponsored_count=sum(
                    item.food is not None
                    and (
                        item.food.sponsored
                        or item.food.press_release
                    )
                    for item in source_admitted
                ),
                access_mode=self._source_access_mode(source),
                ai_tokens=allocated_tokens,
                estimated_cost=allocated_cost,
            )
            metrics.append(metric.model_dump(mode="json"))
        self.run_store.record_source_metrics(
            self.active_run_id, metrics
        )

    @staticmethod
    def _parse_rate(outcome: SourceFetchOutcome) -> float:
        attempts = outcome.published_at_candidate_count
        successes = outcome.published_at_parse_count
        if attempts is None or successes is None:
            return 0.0 if outcome.status == "failure" else 1.0
        if attempts <= 0:
            return 0.0 if outcome.status == "failure" else 1.0
        return max(0.0, min(1.0, successes / attempts))

    def _business_date(self, moment: datetime) -> str:
        if moment.tzinfo is None or moment.utcoffset() is None:
            moment = moment.replace(tzinfo=timezone.utc)
        zone = ZoneInfo(self.config.schedule.timezone)
        return moment.astimezone(zone).strftime("%Y-%m-%d")

    def _source_config_sha256(self) -> str:
        payload = [
            source.model_dump(mode="json")
            for source in sorted(
                self.source_specs_by_id.values(),
                key=lambda source: source.id,
            )
            if source.enabled
        ]
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _source_access_mode(source) -> str:
        explicit = source.options.get("access_mode")
        if explicit:
            return str(explicit)
        if source.options.get("retention_mode") == "metadata_only":
            return "metadata_only"
        note = str(source.options.get("trial_note", ""))
        if "付费" in note:
            return "paywall"
        if "登录" in note or "注册" in note:
            return "login_required"
        return "direct_metadata"

    @staticmethod
    def _ordered_copy(
        item: ContentItem, index: int
    ) -> ContentItem:
        copied = item.model_copy(deep=True)
        copied.metadata["selection_order"] = index
        return copied
