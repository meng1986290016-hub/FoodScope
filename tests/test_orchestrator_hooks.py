import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.models import (
    AIConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import (
    BalancedDigestResult,
    FilteringPipelineResult,
    HorizonOrchestrator,
)


def _item() -> ContentItem:
    return ContentItem(
        id="rss:one",
        source_type=SourceType.RSS,
        title="One",
        url="https://example.com/one",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def _config() -> Config:
    return Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=["en"],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(),
    )


class RecordingStorage:
    def __init__(self):
        self.saved: list[tuple[str, str, str]] = []

    def save_daily_summary(
        self, date: str, markdown: str, language: str = "en"
    ):
        self.saved.append((date, markdown, language))
        return f"/tmp/{date}-{language}.md"


class RecordingOrchestrator(HorizonOrchestrator):
    def __init__(self, config, storage):
        super().__init__(config, storage)
        self.stages: list[str] = []
        self.one_item = _item()

    async def fetch_all_sources(self, since):
        return [self.one_item]

    async def _normalize_items(self, items):
        items[0].metadata["normalized"] = True
        return items

    async def _analyze_content(self, items):
        assert items[0].metadata["normalized"] is True
        items[0].ai_score = 9
        return items

    async def filter_items(self, items, **kwargs):
        return FilteringPipelineResult(
            items=items,
            threshold_count=len(items),
            topic_dedup_count=len(items),
            topic_dedup_removed=0,
            balanced_digest=BalancedDigestResult(items=items),
        )

    async def _expand_twitter_discussion(self, items):
        return None

    def apply_balanced_digest(self, items, **kwargs):
        return BalancedDigestResult(items=items)

    async def _enrich_important_items(self, items):
        items[0].metadata["enriched"] = True

    async def _generate_summary(
        self,
        items,
        date,
        total_fetched,
        language="en",
        summarizer=None,
    ):
        assert items[0].metadata["enriched"] is True
        return "# Hooked summary"

    async def _on_stage(self, stage, payload):
        self.stages.append(stage)


def test_run_calls_extension_hooks_in_pipeline_order(tmp_path, monkeypatch):
    storage = RecordingStorage()
    orchestrator = RecordingOrchestrator(_config(), storage)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

    assert orchestrator.stages == [
        "raw",
        "normalized",
        "scored",
        "filtered",
        "enriched",
        "summary",
    ]
    assert storage.saved[0][1] == "# Hooked summary"


def test_base_delivery_preserves_email_and_webhook_behavior():
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator.console = MagicMock()
    orchestrator.config = SimpleNamespace(
        email=SimpleNamespace(enabled=True)
    )
    orchestrator.storage = SimpleNamespace(
        load_subscribers=lambda: ["reader@example.com"]
    )
    orchestrator.email_manager = MagicMock()
    orchestrator.webhook_notifier = SimpleNamespace(
        send_daily_summary=AsyncMock()
    )
    summarizer = MagicMock()
    items = [_item()]

    asyncio.run(
        orchestrator._deliver_summary(
            summary="# Daily",
            important_items=items,
            all_items_count=10,
            date="2026-07-24",
            lang="en",
            summarizer=summarizer,
        )
    )

    orchestrator.email_manager.send_daily_summary.assert_called_once_with(
        "# Daily",
        "Horizon Summary (EN) - 2026-07-24",
        ["reader@example.com"],
    )
    orchestrator.webhook_notifier.send_daily_summary.assert_awaited_once_with(
        summary="# Daily",
        important_items=items,
        all_items_count=10,
        date="2026-07-24",
        lang="en",
        summarizer=summarizer,
    )
