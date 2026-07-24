"""FoodScope orchestration integrated through Horizon's extension hooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from src.ai.client import create_ai_client
from src.ai.tokens import get_usage_snapshot
from src.ai.summarizer import DailySummarizer
from src.models import Config, ContentItem
from src.orchestrator import (
    BalancedDigestResult,
    FilteringPipelineResult,
    FetchReport,
    HorizonOrchestrator,
)
from src.storage.manager import StorageManager

from .analyzer import FoodContentAnalyzer
from .briefing import BriefFacts, BriefMetadata, RenderedBrief
from .enricher import FoodContentEnricher
from .event_dedup import FoodEventFingerprintStore, merge_food_events
from .evidence import EvidencePolicy
from .loaders import load_profile, load_source_packs
from .models import FoodCategory
from .normalizer import normalize_item
from .rendering import FoodBriefRenderer
from .run_store import FoodRunStore, RunStage
from .selector import FoodProfileSelector, SelectionResult
from .source_health import SourceRunMetric
from .sources.registry import FoodSourceRegistry


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
        self.evidence_policy = EvidencePolicy()
        self.selector = FoodProfileSelector(self.evidence_policy)
        self.selection_result = SelectionResult(items=[])
        self.active_run_id: Optional[str] = None
        self._food_analyzer: FoodContentAnalyzer | None = None
        self._food_enricher: FoodContentEnricher | None = None
        self._brief_facts: BriefFacts | None = None
        self._rendered_brief: RenderedBrief | None = None
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None

    async def run(self, force_hours: int = None) -> None:
        """Create one durable run and delegate execution to Horizon."""
        self.active_run_id = self.run_store.create_run(
            profile_id=self.profile.id
        )
        self._brief_facts = None
        self._rendered_brief = None
        try:
            await super().run(force_hours=force_hours)
        finally:
            self._record_source_metrics()

    async def fetch_all_sources(
        self, since
    ) -> list[ContentItem]:
        """Fetch legacy and FoodScope pack sources independently."""
        parent_items = await super().fetch_all_sources(since)
        parent_outcomes = (
            list(self.last_fetch_report.outcomes)
            if self.last_fetch_report is not None
            else []
        )
        sources = list(self.source_specs_by_id.values())
        food_items: list[ContentItem] = []
        food_outcomes = []
        if sources:
            async with httpx.AsyncClient(timeout=30.0) as client:
                food_items, food_outcomes = await FoodSourceRegistry(
                    client
                ).fetch(sources, since)
        self.last_fetch_report = FetchReport(
            outcomes=parent_outcomes + food_outcomes
        )
        return parent_items + food_items

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
            source_id = item.metadata.get("food_source_id")
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
        stored_payload = payload
        if run_stage == RunStage.ENRICHED and isinstance(payload, list):
            stored_payload = self._with_risk_alerts(payload)
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
        admitted: list[ContentItem] = []
        for item in merged:
            decision = self.evidence_policy.evaluate(item)
            if decision.accepted:
                admitted.append(item)
                continue
            item.metadata["foodscope_evidence_rejected"] = True
            item.metadata["foodscope_evidence_reason"] = decision.reason

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
        admitted = (
            self.selection_result.items
            + self.selection_result.risk_alerts
        )
        self.event_store.remember(admitted)
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
        sections = {
            category.value: [
                item
                for item in selected
                if item.food is not None
                and item.food.category == category
            ]
            for category in FoodCategory
        }
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
            risk_alerts=risk_alerts,
            must_read=selected[:5],
            sections=sections,
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
        self, items: list[ContentItem]
    ) -> list[ContentItem]:
        combined = list(items)
        item_ids = {item.id for item in combined}
        for alert in self.selection_result.risk_alerts:
            if alert.id not in item_ids:
                combined.append(alert)
                item_ids.add(alert.id)
        return combined

    def _record_source_metrics(self) -> None:
        if (
            self.active_run_id is None
            or self.last_fetch_report is None
        ):
            return
        outcomes = {
            outcome.source_name: outcome
            for outcome in self.last_fetch_report.outcomes
            if outcome.source_name in self.source_specs_by_id
        }
        if not outcomes:
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
            len(outcome.items) for outcome in outcomes.values()
        )
        usage = get_usage_snapshot()
        metrics: list[dict] = []
        for source_id, outcome in sorted(outcomes.items()):
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
            candidate_count = len(outcome.items)
            allocated_tokens = (
                round(
                    usage.total_tokens
                    * candidate_count
                    / total_candidates
                )
                if total_candidates
                else 0
            )
            cost_per_thousand = float(
                source.options.get(
                    "estimated_cost_per_1k_tokens", 0.0
                )
            )
            metric = SourceRunMetric(
                source_id=source_id,
                run_id=self.active_run_id,
                fetch_status=outcome.status,
                published_at_parse_rate=(
                    0.0 if outcome.status == "failure" else 1.0
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
                estimated_cost=(
                    allocated_tokens
                    / 1000
                    * cost_per_thousand
                ),
            )
            metrics.append(metric.model_dump(mode="json"))
        self.run_store.record_source_metrics(
            self.active_run_id, metrics
        )

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
