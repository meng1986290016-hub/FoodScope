"""FoodScope orchestration integrated through Horizon's extension hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.ai.client import create_ai_client
from src.ai.summarizer import (
    DailySummarizer,
    _escape_markdown,
    _safe_url,
)
from src.models import Config, ContentItem
from src.orchestrator import (
    BalancedDigestResult,
    FilteringPipelineResult,
    HorizonOrchestrator,
)
from src.storage.manager import StorageManager

from .analyzer import FoodContentAnalyzer
from .enricher import FoodContentEnricher
from .event_dedup import FoodEventFingerprintStore, merge_food_events
from .evidence import EvidencePolicy
from .loaders import load_profile, load_source_packs
from .normalizer import normalize_item
from .run_store import FoodRunStore, RunStage
from .selector import FoodProfileSelector, SelectionResult


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
        try:
            loaded_sources = load_source_packs(self.foodscope_config)
        except FileNotFoundError:
            pack_dir = self.foodscope_config.source_pack_dir
            if pack_dir != Path("data/foodscope/source_packs") or any(
                pack_dir.glob("*.json")
            ):
                raise
            loaded_sources = []
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

    async def run(self, force_hours: int = None) -> None:
        """Create one durable run and delegate execution to Horizon."""
        self.active_run_id = self.run_store.create_run(
            profile_id=self.profile.id
        )
        await super().run(force_hours=force_hours)

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
        """Render a temporary FoodScope Markdown brief."""
        lines = [
            f"# 食界雷达 · 全球食品产业简报（{date}）",
            "",
            (
                f"> 共抓取 {total_fetched} 条，"
                f"入选 {len(items)} 条常规情报，"
                f"另有 {len(self.selection_result.risk_alerts)} 条风险快讯。"
            ),
        ]
        if self.selection_result.risk_alerts:
            lines.extend(["", "## 风险快讯", ""])
            lines.extend(
                self._render_item_line(item)
                for item in self.selection_result.risk_alerts
            )
        lines.extend(["", "## 今日情报", ""])
        if items:
            lines.extend(self._render_item_line(item) for item in items)
        else:
            lines.append("- 今日没有满足当前画像与证据门槛的常规情报。")
        return "\n".join(lines).rstrip() + "\n"

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

    @staticmethod
    def _render_item_line(item: ContentItem) -> str:
        food = item.food
        title = _escape_markdown(
            item.metadata.get("title_zh") or item.title
        )
        url = (
            food.original_source_url
            if food and food.original_source_url
            else str(item.url)
        )
        safe_url = _safe_url(url)
        if safe_url:
            return f"- [{title}]({safe_url})"
        return f"- {title}"
