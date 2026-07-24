# FoodScope Intelligence Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn fetched Horizon items into evidence-checked, cross-language food-industry events selected by one configurable briefing profile.

**Architecture:** `FoodScopeOrchestrator` overrides Horizon's stable fetch/analyze/filter/summary stages while retaining the parent run loop. The fast AI route performs one structured pass per candidate; the analysis route enriches only selected items. Every stage persists Pydantic JSON through `FoodRunStore`.

**Tech Stack:** Python 3.11+, Pydantic 2, asyncio, hashlib, tldextract, pytest.

## Global Constraints

- Consume the public interfaces produced by Plan 1 without renaming them.
- Keep URL deduplication from Horizon and add a seven-day event key for cross-language duplicates.
- Keep importance, profile relevance, opportunity, risk, and evidence quality independent.
- Do not admit regulation, standard, recall, or food-safety claims without official evidence.
- Do not use source collection tier as a ranking boost.
- Isolate an invalid AI result or one failed item; do not fail the batch.

---

### Task 1: Normalize source metadata and merge event duplicates

**Files:**
- Create: `src/foodscope/normalizer.py`
- Create: `src/foodscope/event_dedup.py`
- Test: `tests/foodscope/test_normalizer.py`
- Test: `tests/foodscope/test_event_dedup.py`

**Interfaces:**
- Consumes: `ContentItem`, `FoodSourceSpec`, and optional `FoodIntelligence.event_key`.
- Produces: `normalize_item(item, source) -> ContentItem`
- Produces: `merge_food_events(items) -> list[ContentItem]`
- Produces: `FoodEventFingerprintStore.filter_new()` and `remember()` for the seven-day cross-run window.

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timezone
from src.foodscope.config import FoodSourceSpec
from src.foodscope.event_dedup import FoodEventFingerprintStore, merge_food_events
from src.foodscope.models import CollectionTier, EvidenceTier, FoodCategory, FoodIntelligence, RiskLevel
from src.foodscope.normalizer import normalize_item
from src.models import ContentItem, SourceType


def item(item_id: str, title: str) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.FOOD,
        title=title,
        url=f"https://example.com/{item_id}",
        published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def test_normalizer_attaches_source_contract():
    source = FoodSourceSpec(
        id="M001",
        name="FoodNavigator",
        url="https://example.com",
        adapter="rss",
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        packs=["global_industry", "product_launches"],
        categories=[FoodCategory.PRODUCT_INNOVATION],
    )
    normalized = normalize_item(item("one", "  New   drink  "), source)
    assert normalized.title == "New drink"
    assert normalized.food.source_id == "M001"
    assert normalized.metadata["source_name"] == "FoodNavigator"


def test_cross_language_items_with_same_event_key_merge():
    en = item("en", "Example launches Protein Tea in Japan")
    ja = item("ja", "Example、日本でプロテインティーを発売")
    base = dict(
        category=FoodCategory.PRODUCT_INNOVATION,
        markets=["JP"],
        importance_score=8,
        profile_relevance_score=8,
        opportunity_score=7,
        evidence_quality_score=8,
        risk_level=RiskLevel.NONE,
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        event_key="example|protein-tea|launch|JP|2026-07-24",
    )
    en.food = FoodIntelligence(**base, source_id="M001")
    ja.food = FoodIntelligence(**base, source_id="M075")
    merged = merge_food_events([en, ja])
    assert len(merged) == 1
    assert {link["source_id"] for link in merged[0].metadata["event_sources"]} == {"M001", "M075"}


def test_event_fingerprint_expires_after_seven_days(tmp_path):
    store = FoodEventFingerprintStore(tmp_path / "event-fingerprints.json")
    prior = item("old", "Example launches Protein Tea in Japan")
    prior.food = FoodIntelligence(
        category=FoodCategory.PRODUCT_INNOVATION,
        markets=["JP"],
        importance_score=8,
        profile_relevance_score=8,
        opportunity_score=7,
        evidence_quality_score=8,
        risk_level=RiskLevel.NONE,
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        event_key="example|protein-tea|launch|JP|2026-07-24",
        source_id="M001",
    )
    store.remember([prior], now=datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert store.filter_new([prior], now=datetime(2026, 7, 30, tzinfo=timezone.utc)) == []
    assert store.filter_new([prior], now=datetime(2026, 8, 1, tzinfo=timezone.utc)) == [prior]
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_normalizer.py tests/foodscope/test_event_dedup.py -v
```

Expected: imports fail because the modules do not exist.

- [ ] **Step 3: Implement normalization**

Create `src/foodscope/normalizer.py`:

```python
import re
from src.models import ContentItem
from .config import FoodSourceSpec
from .models import EvidenceTier, FoodCategory, FoodIntelligence, RiskLevel


def normalize_item(item: ContentItem, source: FoodSourceSpec) -> ContentItem:
    item.title = re.sub(r"\s+", " ", item.title).strip()
    item.metadata.update(
        {
            "food_source_id": source.id,
            "source_name": source.name,
            "source_pack_ids": source.packs,
            "markets": source.markets,
            "languages": source.languages,
        }
    )
    if item.food is None:
        category = source.categories[0] if source.categories else FoodCategory.COMPANY_UPDATES
        item_url = str(item.url)
        original_source_url = (
            item.metadata.get("resolved_original_url")
            if source.evidence_tier >= EvidenceTier.DISCOVERY
            else item_url
        )
        item.food = FoodIntelligence(
            category=category,
            markets=source.markets,
            importance_score=0,
            profile_relevance_score=0,
            opportunity_score=0,
            evidence_quality_score=0,
            risk_level=RiskLevel.NONE,
            evidence_tier=source.evidence_tier,
            collection_tier=source.collection_tier,
            source_id=source.id,
            source_pack_ids=source.packs,
            original_source_url=original_source_url,
            evidence_urls=[item_url],
            official_evidence_urls=[item_url] if source.evidence_tier == EvidenceTier.PRIMARY else [],
        )
    return item
```

- [ ] **Step 4: Implement event merging**

Create `src/foodscope/event_dedup.py`:

```python
from collections import defaultdict
from src.models import ContentItem


def merge_food_events(items: list[ContentItem]) -> list[ContentItem]:
    grouped: dict[str, list[ContentItem]] = defaultdict(list)
    unkeyed: list[ContentItem] = []
    for item in items:
        if item.food and item.food.event_key:
            grouped[item.food.event_key].append(item)
        else:
            unkeyed.append(item)

    merged: list[ContentItem] = []
    for event_key in sorted(grouped):
        candidates = sorted(
            grouped[event_key],
            key=lambda candidate: (
                candidate.food.evidence_tier,
                -candidate.food.evidence_quality_score,
                str(candidate.url),
            ),
        )
        primary = candidates[0]
        primary.metadata["event_sources"] = [
            {
                "source_id": candidate.food.source_id,
                "title": candidate.title,
                "url": str(candidate.url),
                "language": candidate.metadata.get("language"),
            }
            for candidate in candidates
        ]
        primary.food.evidence_urls = sorted(
            set(primary.food.evidence_urls + [str(candidate.url) for candidate in candidates])
        )
        primary.food.official_evidence_urls = sorted(
            {
                url
                for candidate in candidates
                for url in candidate.food.official_evidence_urls
            }
        )
        merged.append(primary)
    return merged + unkeyed
```

In the same module, implement `FoodEventFingerprintStore` at `data/state/foodscope-event-fingerprints.json`. It stores `{event_key: last_admitted_at}` as UTC ISO timestamps, prunes entries older than seven days on every read, atomically replaces the JSON file on `remember()`, never records isolated or evidence-rejected events, and returns unkeyed events unchanged.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/foodscope/test_normalizer.py tests/foodscope/test_event_dedup.py -v
uv run pytest
git add src/foodscope tests/foodscope
git commit -m "feat: normalize and merge food industry events"
```

### Task 2: Add structured food analysis

**Files:**
- Create: `src/foodscope/prompts.py`
- Create: `src/foodscope/analyzer.py`
- Test: `tests/foodscope/test_food_analyzer.py`
- Test fixture: `tests/fixtures/foodscope/analysis_response.json`

**Interfaces:**
- Consumes: Horizon `AIClient.complete(system, user)` created from `Config.ai_routes.fast`.
- Produces: `FoodContentAnalyzer.analyze_batch(items) -> list[ContentItem]`
- Produces: populated `ContentItem.food`, translated metadata, and a canonical `event_key`.

- [ ] **Step 1: Write failing analyzer tests**

```python
import json
from pathlib import Path
from tests.foodscope.test_normalizer import item
from src.foodscope.analyzer import FoodContentAnalyzer


class FakeClient:
    async def complete(self, system: str, user: str) -> str:
        return Path("tests/fixtures/foodscope/analysis_response.json").read_text(encoding="utf-8")


async def test_analyzer_populates_five_dimensions_and_event_key():
    analyzed = await FoodContentAnalyzer(FakeClient(), profile_id="balanced").analyze_batch(
        [item("one", "Example launches Protein Tea in Japan")]
    )
    food = analyzed[0].food
    assert food.importance_score == 8.0
    assert food.opportunity_score == 7.0
    assert food.evidence_quality_score == 8.0
    assert food.event_key == "example|protein-tea|launch|JP|2026-07-24"
    assert analyzed[0].metadata["title_zh"] == "Example 在日本推出蛋白茶"
```

Create the fixture as one complete valid analysis object:

```json
{
  "relevant": true,
  "title_zh": "Example 在日本推出蛋白茶",
  "summary_zh": "Example 在日本上市一款蛋白茶新品。产品将高蛋白诉求与即饮茶形态结合。首发渠道为日本零售市场。",
  "category": "product_innovation",
  "markets": ["JP"],
  "product_tags": ["tea", "protein drink"],
  "ingredient_tags": ["protein"],
  "technology_tags": [],
  "company_tags": ["Example"],
  "importance_score": 8.0,
  "profile_relevance_score": 8.5,
  "opportunity_score": 7.0,
  "evidence_quality_score": 8.0,
  "risk_level": "none",
  "risk_reason": "",
  "event_key": "example|protein-tea|launch|JP|2026-07-24",
  "sponsored": false,
  "press_release": false,
  "product_launch": {
    "brand": "Example",
    "company": "Example Foods",
    "product_name": "Protein Tea",
    "launch_markets": ["JP"],
    "launch_date": "2026-07-24",
    "audience": ["active adults"],
    "ingredients": ["protein"],
    "flavors": ["tea"],
    "format": "ready-to-drink",
    "claims": ["high protein"],
    "package_size": "350 ml",
    "price": null,
    "channels": ["retail"],
    "launch_type": "new_product"
  }
}
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_food_analyzer.py -v
```

Expected: import fails because `FoodContentAnalyzer` does not exist.

- [ ] **Step 3: Implement the validated response model and analyzer**

In `src/foodscope/analyzer.py`, define the complete response contract before the analyzer:

```python
import asyncio
from typing import Optional
from pydantic import BaseModel, Field, ValidationError, model_validator
from src.ai.utils import parse_json_response
from src.models import ContentItem
from .models import FoodCategory, FoodIntelligence, ProductLaunchDetails, RiskLevel
from .prompts import FOOD_ANALYSIS_SYSTEM, FOOD_ANALYSIS_USER


class FoodAnalysisResult(BaseModel):
    relevant: bool
    title_zh: str = ""
    summary_zh: str = ""
    category: Optional[FoodCategory] = None
    markets: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    ingredient_tags: list[str] = Field(default_factory=list)
    technology_tags: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    importance_score: Optional[float] = Field(default=None, ge=0, le=10)
    profile_relevance_score: Optional[float] = Field(default=None, ge=0, le=10)
    opportunity_score: Optional[float] = Field(default=None, ge=0, le=10)
    evidence_quality_score: Optional[float] = Field(default=None, ge=0, le=10)
    risk_level: Optional[RiskLevel] = None
    risk_reason: str = ""
    event_key: Optional[str] = None
    sponsored: bool = False
    press_release: bool = False
    product_launch: Optional[ProductLaunchDetails] = None

    @model_validator(mode="after")
    def require_analysis_for_relevant_item(self):
        if not self.relevant:
            return self
        required = {
            "title_zh": self.title_zh,
            "summary_zh": self.summary_zh,
            "category": self.category,
            "importance_score": self.importance_score,
            "profile_relevance_score": self.profile_relevance_score,
            "opportunity_score": self.opportunity_score,
            "evidence_quality_score": self.evidence_quality_score,
            "risk_level": self.risk_level,
            "event_key": self.event_key,
        }
        missing = [name for name, value in required.items() if value is None or value == ""]
        if missing:
            raise ValueError(f"relevant item missing fields: {', '.join(missing)}")
        return self


class FoodContentAnalyzer:
    def __init__(
        self,
        client,
        profile_id: str,
        max_attempts: int = 3,
        concurrency: int = 4,
        timeout_seconds: float = 60.0,
    ):
        self.client = client
        self.profile_id = profile_id
        self.max_attempts = max_attempts
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout_seconds = timeout_seconds

    async def analyze_batch(self, items: list[ContentItem]) -> list[ContentItem]:
        return await asyncio.gather(*(self._safe_analyze(item) for item in items))

    async def _safe_analyze(self, item: ContentItem) -> ContentItem:
        result = None
        for attempt in range(self.max_attempts):
            try:
                async with self.semaphore:
                    async with asyncio.timeout(self.timeout_seconds):
                        response = await self.client.complete(
                            system=FOOD_ANALYSIS_SYSTEM,
                            user=FOOD_ANALYSIS_USER.format(
                                profile_id=self.profile_id,
                                title=item.title,
                                url=str(item.url),
                                content=(item.content or "")[:4000],
                                source=item.metadata.get("source_name", item.source_type.value),
                            ),
                        )
                result = FoodAnalysisResult.model_validate(parse_json_response(response))
                break
            except (ValidationError, TypeError, ValueError, RuntimeError, TimeoutError):
                item.metadata["foodscope_analysis_attempts"] = attempt + 1
        if result is None:
            item.ai_score = 0.0
            item.ai_reason = f"Food analysis failed after {self.max_attempts} attempts"
            item.metadata["foodscope_isolated"] = True
            return item
        if not result.relevant:
            item.ai_score = 0.0
            item.ai_reason = "Not relevant to the food industry"
            return item
        existing = item.food
        assert existing is not None
        assert result.category is not None
        assert result.importance_score is not None
        assert result.profile_relevance_score is not None
        assert result.opportunity_score is not None
        assert result.evidence_quality_score is not None
        assert result.risk_level is not None
        assert result.event_key is not None
        item.food = FoodIntelligence(
            category=result.category,
            markets=result.markets,
            product_tags=result.product_tags,
            ingredient_tags=result.ingredient_tags,
            technology_tags=result.technology_tags,
            company_tags=result.company_tags,
            importance_score=result.importance_score,
            profile_relevance_score=result.profile_relevance_score,
            opportunity_score=result.opportunity_score,
            evidence_quality_score=result.evidence_quality_score,
            risk_level=result.risk_level,
            risk_reason=result.risk_reason,
            evidence_tier=existing.evidence_tier,
            collection_tier=existing.collection_tier,
            source_id=existing.source_id,
            source_pack_ids=existing.source_pack_ids,
            event_key=result.event_key,
            original_source_url=existing.original_source_url,
            evidence_urls=existing.evidence_urls,
            official_evidence_urls=existing.official_evidence_urls,
            sponsored=result.sponsored,
            press_release=result.press_release,
            product_launch=result.product_launch,
        )
        item.ai_score = result.importance_score
        item.ai_reason = f"importance={result.importance_score}; opportunity={result.opportunity_score}"
        item.ai_summary = result.summary_zh
        item.metadata["title_zh"] = result.title_zh
        item.metadata["summary_zh"] = result.summary_zh
        return item
```

Use a system prompt that demands one JSON object and a three-sentence Chinese summary, forbids invented regulations/dates/limits, defines all eight categories and five dimensions, and requires `product_launch` only for real product-launch events.

- [ ] **Step 4: Add invalid JSON and irrelevant-item tests**

Add one fake response containing malformed JSON and one containing exactly `{"relevant": false}`. Assert malformed results are isolated and irrelevant results receive score `0.0` without failing the batch.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/foodscope/test_food_analyzer.py -v
uv run pytest
git add src/foodscope tests/foodscope tests/fixtures/foodscope
git commit -m "feat: add structured food intelligence analysis"
```

### Task 3: Enforce evidence and select by profile

**Files:**
- Create: `src/foodscope/evidence.py`
- Create: `src/foodscope/selector.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/foodscope/test_evidence.py`
- Test: `tests/foodscope/test_selector.py`

**Interfaces:**
- Produces: `EvidenceDecision`
- Produces: `EvidencePolicy.evaluate(item) -> EvidenceDecision`
- Produces: `SelectionResult(items, risk_alerts, rejected, category_counts, source_counts)`
- Produces: `FoodProfileSelector.select(items, profile) -> SelectionResult`

- [ ] **Step 1: Write evidence and selector tests**

Cover these exact cases:

```python
def test_safety_item_without_official_url_is_rejected():
    decision = EvidencePolicy().evaluate(safety_item(official_evidence_urls=[]))
    assert decision.accepted is False
    assert decision.reason == "official evidence required"


def test_tier_three_item_requires_primary_or_two_independent_domains():
    decision = EvidencePolicy().evaluate(discovery_item(evidence_urls=["https://one.example/a"]))
    assert decision.accepted is False


def test_high_risk_is_alert_but_does_not_consume_regular_quota():
    result = FoodProfileSelector().select(items=[high_risk_item(), market_item()], profile=market_profile())
    assert result.risk_alerts == [high_risk_item()]
    assert result.items == [market_item()]


def test_collection_tier_does_not_change_rank():
    core = scored_item(source_id="A", collection_tier="core", importance=7)
    extended = scored_item(source_id="B", collection_tier="extended", importance=8)
    result = FoodProfileSelector().select([core, extended], balanced_profile())
    assert result.items[0].food.source_id == "B"
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_evidence.py tests/foodscope/test_selector.py -v
```

Expected: imports fail.

- [ ] **Step 3: Implement evidence rules**

`EvidencePolicy.evaluate()` must:

1. Reject isolated/invalid items.
2. Require at least one URL in `food.official_evidence_urls` for `REGULATIONS_STANDARDS` and `FOOD_SAFETY_RECALLS`.
3. Accept tier 1 and tier 2 items after rule 2.
4. Accept tier 3 only with `original_source_url` or evidence from at least two distinct registrable domains.
5. Accept tier 4 only after `original_source_url` is present and `item.metadata["linked_evidence_tier"]` is `1`, `2`, or `3`; use that value as the effective tier.
6. Reduce `evidence_quality_score` by `2.0`, floor `0`, for sponsored or press-release-only material.

Add `tldextract>=5.1.0` and initialize `TLDExtract(suffix_list_urls=())` so evidence checks are deterministic and never download the public suffix list at run time.

Use:

```python
from dataclasses import dataclass
import tldextract
from src.models import ContentItem
from .models import EvidenceTier, FoodCategory


@dataclass(frozen=True)
class EvidenceDecision:
    accepted: bool
    reason: str
    effective_tier: EvidenceTier


OFFICIAL_CATEGORIES = {
    FoodCategory.REGULATIONS_STANDARDS,
    FoodCategory.FOOD_SAFETY_RECALLS,
}
```

- [ ] **Step 4: Implement deterministic selection**

Define `SelectionResult` as a Pydantic model so Plan 4 can hash and render one canonical fact snapshot:

```python
from pydantic import BaseModel, Field


class SelectionResult(BaseModel):
    items: list[ContentItem]
    risk_alerts: list[ContentItem] = Field(default_factory=list)
    rejected: list[ContentItem] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
```

Rank admitted regular items by:

```python
base_rank = (
    0.35 * food.importance_score
    + 0.25 * food.profile_relevance_score
    + 0.20 * food.opportunity_score
    + 0.20 * food.evidence_quality_score
)
topic_multiplier = 1.0 + profile.topic_weights[food.category]
market_multiplier = 1.0 + max(
    (profile.market_weights.get(market, 0.0) for market in food.markets),
    default=0.0,
)
final_rank = base_rank * topic_multiplier * market_multiplier
```

Use `base_rank` for the `minimum_score` gate and `final_rank` for ordering. Break ties by lower evidence tier, newer `published_at`, then URL. Put items at or above `profile.risk_override_min` into `risk_alerts` before regular selection.

For regular items:

1. define low-priority exploration candidates as categories whose topic weight is below the median profile topic weight;
2. reserve at most `exploration_slots` for the highest-ranked low-priority candidates;
3. fill remaining slots by `final_rank`, never exceeding `max_per_source`;
4. fill unused exploration slots from the remaining ranked pool;
5. stop at `max_items`;
6. for `balanced`, define commercial/technical categories as product innovation, ingredients/technology, packaging/labeling, consumer trends, retail/foodservice, and company updates; when enough admitted commercial candidates exist to meet `ceil(selected_count * commercial_min_ratio)`, replace the lowest-ranked non-commercial selections with the highest-ranked unselected commercial candidates while preserving the source cap.

Save `food.selection_reason` with profile ID, the four raw scores, topic multiplier, market multiplier, evidence tier, and final rank. Collection tier must not appear in either rank calculation.

- [ ] **Step 5: Verify and commit**

```bash
uv lock
uv run pytest tests/foodscope/test_evidence.py tests/foodscope/test_selector.py -v
uv run pytest
git add src/foodscope tests/foodscope pyproject.toml uv.lock
git commit -m "feat: enforce food evidence and profile selection"
```

### Task 4: Persist resumable run stages

**Files:**
- Create: `src/foodscope/run_store.py`
- Test: `tests/foodscope/test_run_store.py`

**Interfaces:**
- Produces: `RunStage`
- Produces: `FoodRunStore.create_run()`, `save_stage()`, `load_stage()`, `latest_resumable_run()`, and `record_delivery()`.

- [ ] **Step 1: Write failing run-store tests**

```python
from src.foodscope.run_store import FoodRunStore, RunStage
from tests.foodscope.test_normalizer import item


def test_stage_round_trip_and_resume(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    store.save_stage(run_id, RunStage.RAW, [item("one", "Title")])
    restored = store.load_stage(run_id, RunStage.RAW)
    assert restored[0].id == "one"
    assert store.latest_resumable_run() == (run_id, RunStage.RAW)


def test_delivery_records_are_idempotent(tmp_path):
    store = FoodRunStore(tmp_path)
    run_id = store.create_run(profile_id="balanced")
    store.record_delivery(run_id, "email", "success", artifact_id="sha256:test")
    store.record_delivery(run_id, "email", "success", artifact_id="sha256:test")
    assert store.load_manifest(run_id)["deliveries"]["email"]["attempts"] == 1
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_run_store.py -v
```

Expected: import fails.

- [ ] **Step 3: Implement atomic stage storage**

Define:

```python
from enum import StrEnum


class RunStage(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    SCORED = "scored"
    FILTERED = "filtered"
    ENRICHED = "enriched"
    SUMMARY = "summary"
```

`save_stage()` accepts `list[ContentItem] | dict | str`: item stages use `[item.model_dump(mode="json")]`, while the summary stage stores a dictionary or string. `load_stage()` reconstructs `ContentItem` objects for the five item stages and returns the stored summary payload unchanged. Write each stage to `data/runs/{run_id}/{stage}.json` using a temporary sibling file, `flush()`, `os.fsync()`, and `Path.replace()`. Store `manifest.json` with profile ID, schema version, created/updated timestamps, completed stages, counts, errors, isolation entries, token usage, and delivery results. Treat a successful channel/fact-hash pair as idempotent.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/foodscope/test_run_store.py -v
uv run pytest
git add src/foodscope/run_store.py tests/foodscope/test_run_store.py
git commit -m "feat: persist resumable FoodScope run stages"
```

### Task 5: Integrate FoodScope stages into Horizon orchestration

**Files:**
- Modify: `src/orchestrator.py`
- Modify: `src/foodscope/orchestrator.py`
- Create: `src/foodscope/enricher.py`
- Test: `tests/foodscope/test_foodscope_orchestrator.py`
- Test: `tests/foodscope/test_food_enricher.py`
- Test fixture: `tests/fixtures/foodscope/enrichment_response.json`
- Modify: `tests/test_summarizer.py`

**Interfaces:**
- Consumes: analyzer, event merge, evidence, selector, loader, and run store services.
- Produces: a FoodScope run that still uses Horizon's parent run loop.
- Produces: `FoodContentEnricher.enrich(items) -> list[ContentItem]`.

- [ ] **Step 1: Write a failing orchestration smoke test**

Use fake fetch, AI, enrichment, and summary dependencies. Assert this stage order:

```python
assert completed_stages == [
    "raw",
    "normalized",
    "scored",
    "filtered",
    "enriched",
    "summary",
]
```

Also assert one malformed item is in the manifest's isolation count while a valid item reaches the summary.

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_foodscope_orchestrator.py -v
```

Expected: the pass-through subclass does not save FoodScope stages or select by profile.

- [ ] **Step 3: Add generic Horizon stage and delivery hooks**

Modify `src/orchestrator.py` so the parent run loop:

1. calls `_normalize_items()` after URL deduplication and before AI analysis;
2. calls `_on_stage()` after raw fetch, normalization, analysis, final filtering/profile balance, enrichment, and summary generation;
3. calls its existing `_generate_summary()` method rather than instantiating `DailySummarizer` inline.

Add no-op-compatible base hooks:

```python
async def _normalize_items(self, items: list[ContentItem]) -> list[ContentItem]:
    return items


async def _on_stage(self, stage: str, payload: object) -> None:
    return None


def _create_summarizer(self) -> DailySummarizer:
    return DailySummarizer()
```

Use this factory for webhook item rendering. Move existing email/webhook calls into:

```python
async def _deliver_summary(
    self,
    summary: str,
    important_items: list[ContentItem],
    all_items_count: int,
    date: str,
    lang: str,
    summarizer: DailySummarizer,
) -> None:
    """Preserve the existing Horizon email and webhook behavior."""
```

The base implementation must contain the prior behavior unchanged. Add upstream regression tests for call order, summary output, email, and webhook before refactoring.

- [ ] **Step 4: Add selected-item food enrichment**

Create `src/foodscope/enricher.py` with a validated response model containing these exact string fields:

```python
from pydantic import BaseModel


class FoodEnrichmentResult(BaseModel):
    what_happened_zh: str
    why_it_matters_zh: str
    rd_significance_zh: str = ""
    opportunity_signal_zh: str
    risk_signal_zh: str = ""
    recommended_action_zh: str
```

`FoodContentEnricher.enrich()` receives only the selected regular items and risk alerts. It uses the client created from `Config.ai_routes.analysis`, applies that route's `concurrency`, `timeout_seconds`, and `max_attempts`, asks for one JSON object per item, copies the six fields to `ContentItem.food`, and isolates only the failed item after its attempts are exhausted. The prompt must require evidence-bounded language, prohibit invented legal conclusions and market numbers, and use an empty string when no R&D or risk implication is supported.

Create `tests/fixtures/foodscope/enrichment_response.json`:

```json
{
  "what_happened_zh": "Example 在日本推出一款 350 毫升即饮蛋白茶。",
  "why_it_matters_zh": "它把高蛋白诉求带入茶饮形态，提供了跨品类创新样本。",
  "rd_significance_zh": "需要关注蛋白体系在茶基底中的稳定性与口感。",
  "opportunity_signal_zh": "中国品牌可验证运动营养与即饮茶人群的交集。",
  "risk_signal_zh": "功能宣称与实际营养含量需要按目标市场规则核验。",
  "recommended_action_zh": "跟踪日本渠道反馈，并先进行小规模配方和消费者测试。"
}
```

Write tests for the valid fixture, one malformed response followed by a successful retry, and three invalid responses that isolate one item while another item completes.

- [ ] **Step 5: Override FoodScope stages**

In `FoodScopeOrchestrator.__init__`, load the active profile, create the fast and analysis clients from `config.ai_routes`, pass each route's concurrency/timeout/attempt settings to its service, and initialize `FoodRunStore(Path(storage.data_dir) / "runs")`. Override:

- `run()` as a thin wrapper that creates one run ID and then delegates to `super().run()`;
- `_normalize_items()` to map loaded source IDs to `FoodSourceSpec` and call `normalize_item()`;
- `_on_stage()` to serialize the current stage under the active run ID;
- `_analyze_content()` to call `FoodContentAnalyzer`;
- `filter_items()` to call `merge_food_events()` first, then run evidence decisions on each merged event;
- `apply_balanced_digest()` to filter previously admitted event keys through `FoodEventFingerprintStore`, call `FoodProfileSelector`, remember newly admitted event keys, retain `SelectionResult`, and return a Horizon `BalancedDigestResult` containing `selection.items`;
- `_enrich_important_items()` to enrich the selected regular items and risk alerts with `FoodContentEnricher`;
- `_generate_summary()` to use a temporary FoodScope Markdown renderer that lists risk alerts followed by selected titles until Plan 4 replaces it;
- stage boundaries to save the exact run artifacts.

Keep `fetch_all_sources()` calling `super()`; Plan 3 appends FoodScope pack sources.

- [ ] **Step 6: Verify base and FoodScope modes**

```bash
uv run pytest tests/foodscope/test_foodscope_orchestrator.py tests/foodscope/test_food_enricher.py tests/test_balanced_digest.py tests/test_summarizer.py tests/test_webhook.py -v
uv run pytest
```

Expected: all tests pass in both legacy and FoodScope modes.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator.py src/foodscope/orchestrator.py tests
git commit -m "feat: integrate FoodScope intelligence stages"
```
