# FoodScope Source Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the screened source catalog into configurable, testable source packs with compliant adapters and measurable 14-day trial performance.

**Architecture:** A registry maps manifest adapter names to small `BaseFoodAdapter` implementations. Static JSON manifests are generated from the audited Markdown decisions, committed to the repository, then enriched with adapter options and operational tiers from probe and trial evidence.

**Tech Stack:** Python 3.11+, httpx, feedparser, BeautifulSoup, pypdf, Pydantic 2, pytest.

## Global Constraints

- Include all and only the 59 retained `M` candidates in non-social manifests.
- Include exactly `S021`, `S022`, `S023`, `S028`, `S029`, and `S038` in `x_watch`, all disabled.
- Include no Reddit candidate or FoodScope Reddit example.
- Respect robots, terms, rate limits, paywalls, and copyright; collect metadata and permitted short summaries rather than protected full text.
- Regulations, recalls, standards, and food safety require official evidence URLs.
- A single source failure returns `SourceFetchOutcome(status="failure")` and does not abort other sources.

---

### Task 1: Add adapter registry and safe generic adapters

**Files:**
- Create: `src/foodscope/sources/__init__.py`
- Create: `src/foodscope/sources/base.py`
- Create: `src/foodscope/sources/registry.py`
- Create: `src/foodscope/sources/rss.py`
- Create: `src/foodscope/sources/json_api.py`
- Create: `src/foodscope/sources/html_list.py`
- Create: `src/foodscope/sources/documents.py`
- Modify: `src/foodscope/orchestrator.py`
- Modify: `pyproject.toml`
- Test: `tests/foodscope/sources/test_registry.py`
- Test: `tests/foodscope/sources/test_adapters.py`
- Test: `tests/foodscope/sources/test_orchestrator_fetch.py`
- Test fixtures: `tests/fixtures/foodscope/sources/feed.xml`
- Test fixtures: `tests/fixtures/foodscope/sources/list.html`
- Test fixtures: `tests/fixtures/foodscope/sources/api.json`

**Interfaces:**
- Produces: `BaseFoodAdapter.fetch(source, since) -> list[ContentItem]`
- Produces: `FoodSourceRegistry.fetch(sources, since) -> tuple[list[ContentItem], list[SourceFetchOutcome]]`
- Extends: `FoodScopeOrchestrator.fetch_all_sources(since) -> list[ContentItem]`

- [ ] **Step 1: Write failing registry tests**

```python
from datetime import datetime, timezone
import httpx
from src.foodscope.sources.registry import FoodSourceRegistry
from tests.foodscope.source_factories import rss_source


async def test_registry_fetches_each_source_independently():
    registry = FoodSourceRegistry(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_source_responses))
    )
    items, outcomes = await registry.fetch(
        [rss_source("good"), rss_source("broken")],
        datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    assert len(items) == 1
    assert [outcome.status for outcome in outcomes] == ["success", "failure"]
```

Add adapter tests asserting:

- RSS honors `since`, title, link, timestamp, and short description.
- JSON API uses configured `items_path`, `title_field`, `url_field`, `date_field`, and `content_field`.
- HTML list uses configured `item_selector`, `title_selector`, `link_selector`, and `date_selector`.
- Document index emits the linked document URL and metadata without embedding an entire PDF/HWPX body.
- An unsafe private-network URL is rejected through Horizon's URL security helper.

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/sources -v
```

Expected: source modules do not exist.

- [ ] **Step 3: Implement the adapter contract**

Create `src/foodscope/sources/base.py`:

```python
from abc import ABC, abstractmethod
from datetime import datetime
import httpx
from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem


class BaseFoodAdapter(ABC):
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    async def fetch(self, source: FoodSourceSpec, since: datetime) -> list[ContentItem]:
        raise NotImplementedError
```

Each adapter must emit `SourceType.FOOD`, an ID formatted `food:{source.id}:{native_id}`, UTC-aware timestamps, and source metadata needed by `normalize_item()`.

- [ ] **Step 4: Implement the registry**

Create `src/foodscope/sources/registry.py`:

```python
import asyncio
from datetime import datetime
import httpx
from src.foodscope.config import FoodSourceSpec
from src.orchestrator import SourceFetchOutcome
from .base import BaseFoodAdapter
from .documents import DocumentIndexAdapter
from .html_list import HTMLListAdapter
from .json_api import JSONAPIAdapter
from .rss import RSSFoodAdapter


ADAPTERS: dict[str, type[BaseFoodAdapter]] = {
    "rss": RSSFoodAdapter,
    "json_api": JSONAPIAdapter,
    "html_list": HTMLListAdapter,
    "document_index": DocumentIndexAdapter,
}


class FoodSourceRegistry:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client

    async def fetch(
        self,
        sources: list[FoodSourceSpec],
        since: datetime,
    ) -> tuple[list, list[SourceFetchOutcome]]:
        async def one(source: FoodSourceSpec) -> SourceFetchOutcome:
            try:
                adapter_type = ADAPTERS[source.adapter]
                items = await adapter_type(self.client).fetch(source, since)
                status = "success" if items else "empty"
                return SourceFetchOutcome(source.id, status, items=items)
            except Exception as exc:
                return SourceFetchOutcome(
                    source.id,
                    "failure",
                    error=f"{type(exc).__name__}: {exc}",
                )
        outcomes = await asyncio.gather(*(one(source) for source in sources if source.enabled))
        return [item for outcome in outcomes for item in outcome.items], list(outcomes)
```

- [ ] **Step 5: Add PDF support and verify**

Override `FoodScopeOrchestrator.fetch_all_sources()` to:

1. await `super().fetch_all_sources(since)` and retain the parent `FetchReport.outcomes`;
2. load configured FoodScope sources with `load_source_packs()`;
3. fetch them through one shared `httpx.AsyncClient` and `FoodSourceRegistry`;
4. combine parent and FoodScope outcomes into one `FetchReport`;
5. return the combined item list and leave URL/event deduplication to the downstream stages.

The orchestration test must enable one fixture source, assert that parent and FoodScope outcomes both remain in `last_fetch_report`, and assert one failed FoodScope source does not remove successful parent items.

Then add `pypdf>=5.0.0` to `pyproject.toml`. The document adapter may extract a bounded first-page text sample only when terms permit; otherwise it emits document title, date, URL, media type, and `content=None`.

```bash
uv lock
uv run pytest tests/foodscope/sources tests/foodscope/test_foodscope_orchestrator.py -v
uv run pytest
git add src/foodscope tests/foodscope tests/fixtures/foodscope/sources pyproject.toml uv.lock
git commit -m "feat: add safe FoodScope source adapters"
```

### Task 2: Generate curated media and regional manifests

**Files:**
- Create: `scripts/build_foodscope_source_packs.py`
- Create: `tests/foodscope/test_source_pack_builder.py`
- Create or regenerate:
  - `data/foodscope/source_packs/global_industry.json`
  - `data/foodscope/source_packs/product_launches.json`
  - `data/foodscope/source_packs/ingredients_rd.json`
  - `data/foodscope/source_packs/packaging_processing.json`
  - `data/foodscope/source_packs/retail_foodservice.json`
  - `data/foodscope/source_packs/japan.json`
  - `data/foodscope/source_packs/korea.json`
  - `data/foodscope/source_packs/southeast_asia.json`
  - `data/foodscope/source_packs/research_data.json`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-23-foodscope-industry-media-longlist.md`.
- Produces: deterministic static manifests containing the 59 retained `M` sources.

- [ ] **Step 1: Write a failing exact-set test**

```python
from pathlib import Path
from src.foodscope.config import SourcePackManifest
import json

EXPECTED_KEEP = {
    "M001","M002","M003","M004","M005","M006","M007","M009","M011","M012",
    "M017","M019","M020","M021","M022","M024","M026","M028","M030","M032",
    "M033","M034","M035","M036","M039","M040","M042","M044","M050","M055",
    "M056","M058","M060","M061","M063","M064","M065","M075","M076","M079",
    "M080","M084","M085","M086","M087","M089","M090","M091","M092","M093",
    "M094","M098","M099","M105","M110","M111","M112","M113","M115",
}


def test_non_social_manifests_cover_exact_keep_set():
    found = set()
    for path in Path("data/foodscope/source_packs").glob("*.json"):
        if path.stem in {"official_evidence", "discovery_queries", "x_watch"}:
            continue
        manifest = SourcePackManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
        found.update(source.id for source in manifest.sources)
    assert found == EXPECTED_KEEP
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_source_pack_builder.py -v
```

Expected: manifests do not exist.

- [ ] **Step 3: Implement deterministic Markdown extraction**

The builder must parse the candidate tables for ID, linked name, URL, market/language, signal, initial grade, and note; parse the decision table; emit only decision `keep`; and fail if its set differs from `EXPECTED_KEEP`.

Use this primary pack mapping by numeric ID:

```python
PRIMARY_PACK_RANGES = (
    (1, 18, "global_industry"),
    (19, 36, "ingredients_rd"),
    (37, 54, "packaging_processing"),
    (55, 74, "retail_foodservice"),
    (75, 88, "japan"),
    (89, 97, "korea"),
    (98, 109, "southeast_asia"),
    (110, 120, "research_data"),
)

PRODUCT_LAUNCH_IDS = {
    "M001","M002","M003","M004","M019","M021","M030","M035",
    "M055","M075","M076","M089","M090","M091","M092","M098","M105",
}
```

Every retained source goes to one primary pack; `PRODUCT_LAUNCH_IDS` additionally go to `product_launches`. Generated sources start with `adapter: "html_list"`, `collection_tier: "extended"`, `enabled: true`, and pack/category metadata derived from the candidate row. Adapter options are refined by Task 3.

- [ ] **Step 4: Generate, validate, and commit**

```bash
uv run python scripts/build_foodscope_source_packs.py
git add data/foodscope/source_packs
uv run python scripts/build_foodscope_source_packs.py
uv run pytest tests/foodscope/test_source_pack_builder.py tests/foodscope/test_loaders.py -v
git diff --exit-code -- data/foodscope/source_packs
git add scripts/build_foodscope_source_packs.py data/foodscope/source_packs tests/foodscope/test_source_pack_builder.py
git commit -m "data: add curated FoodScope media source packs"
```

Expected: the second generator run creates no diff and exactly 59 unique `M` IDs are covered.

### Task 3: Add official evidence and discovery-query packs

**Files:**
- Create: `scripts/build_foodscope_official_query_packs.py`
- Create: `data/foodscope/source_packs/official_evidence.json`
- Create: `data/foodscope/source_packs/discovery_queries.json`
- Create: `tests/foodscope/test_official_and_query_packs.py`
- Modify: `src/foodscope/sources/registry.py`
- Create: `src/foodscope/sources/discovery_query.py`
- Create: `src/foodscope/sources/google_news.py`
- Create: `src/foodscope/sources/gdelt.py`

**Interfaces:**
- Produces: official evidence sources with evidence tier 1.
- Produces: 20 multilingual query sources with evidence tier 3 and collection tier `discovery`.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_official_sources_are_primary_and_queries_are_discovery():
    official = load_manifest("official_evidence")
    queries = load_manifest("discovery_queries")
    assert all(source.evidence_tier == 1 for source in official.sources)
    assert len(queries.sources) == 20
    assert all(source.evidence_tier == 3 for source in queries.sources)
    assert all(source.collection_tier == "discovery" for source in queries.sources)
```

Also assert each official source declares an adapter and all concrete options required by that adapter. Assert these exact IDs:

```python
EXPECTED_OFFICIAL = {
    "global_codex_news", "global_wto_sps", "us_fda_food_recalls",
    "us_fda_outbreaks", "us_openfda_enforcement", "us_fda_food_guidance",
    "us_fsis_recalls", "eu_ec_food_safety_news", "eu_rasff", "eu_efsa_news",
    "eu_eurlex_food_law", "uk_fsa_food_alerts", "jp_caa_food_labeling",
    "jp_caa_food_recalls", "jp_caa_food_standards", "kr_mfds_press",
    "kr_mfds_standards", "sg_sfa_food_alerts", "sg_sfa_newsroom", "vn_vfa_news",
}

EXPECTED_QUERIES = {
    "en_product_launch", "en_ingredient_innovation", "en_fermentation",
    "en_alternative_protein", "en_functional_food", "en_reformulation",
    "en_food_packaging", "en_processing_technology", "en_consumer_trends",
    "en_retail_foodservice", "en_brand_strategy", "en_investment_ma",
    "en_capacity_expansion", "ja_product_launch", "ja_ingredient_technology",
    "ja_market_retail", "ko_product_launch", "ko_ingredient_technology",
    "ko_market_retail", "en_southeast_asia",
}
```

- [ ] **Step 2: Build static manifests from the approved catalog**

Implement `scripts/build_foodscope_official_query_packs.py` to parse sections 2.1 and 3.2 of `docs/superpowers/specs/2026-07-23-foodscope-source-catalog.md`. The script must:

1. fail unless the parsed official and query IDs equal `EXPECTED_OFFICIAL` and `EXPECTED_QUERIES`;
2. preserve every linked URL and query string exactly;
3. map RSS rows to `rss`, JSON API rows to `json_api`, rows mentioning PDF or HWPX to `document_index`, and remaining official rows to `html_list`;
4. set official sources to evidence tier `1`, with recall and alert sources `core` and all other official sources `extended`;
5. emit one `discovery_query` source per query row with its providers, query, languages, markets, category hint, provider limit `20`, post-dedup limit `12`, evidence tier `3`, and collection tier `discovery`;
6. write both JSON files with sorted keys, two-space indentation, and a trailing newline.

Implement `DiscoveryQueryAdapter` as a small dispatcher over `GoogleNewsFoodAdapter` and `GDELTFoodAdapter`. Use existing Horizon Google News/GDELT request behavior, but emit `SourceType.FOOD`, the query ID, provider, target markets, languages, and category hint on every item. Japanese and Korean query manifests enable only Google News; English manifests enable both providers.

- [ ] **Step 3: Run focused tests and probe fixtures**

```bash
uv run python scripts/build_foodscope_official_query_packs.py
git add data/foodscope/source_packs/official_evidence.json data/foodscope/source_packs/discovery_queries.json
uv run python scripts/build_foodscope_official_query_packs.py
uv run pytest tests/foodscope/test_official_and_query_packs.py tests/test_gdelt.py tests/test_google_news.py -v
git diff --exit-code -- data/foodscope/source_packs/official_evidence.json data/foodscope/source_packs/discovery_queries.json
uv run pytest
git add scripts/build_foodscope_official_query_packs.py src/foodscope/sources data/foodscope/source_packs tests/foodscope
git commit -m "data: add official and discovery source packs"
```

### Task 4: Add the disabled X watch pack

**Files:**
- Create: `data/foodscope/source_packs/x_watch.json`
- Create: `src/foodscope/sources/x_official_api.py`
- Modify: `src/foodscope/sources/registry.py`
- Modify: `src/foodscope/loaders.py`
- Test: `tests/foodscope/test_x_watch_pack.py`
- Test: `tests/foodscope/sources/test_x_official_api.py`

**Interfaces:**
- Produces: metadata-only, disabled weak-signal definitions.

- [ ] **Step 1: Write the exact policy test**

```python
def test_x_watch_contains_only_approved_disabled_accounts():
    manifest = load_manifest("x_watch")
    assert {source.id for source in manifest.sources} == {
        "S021", "S022", "S023", "S028", "S029", "S038"
    }
    assert all(source.enabled is False for source in manifest.sources)
    assert all(source.evidence_tier == 4 for source in manifest.sources)
    assert all(source.options["retention_mode"] == "metadata_only" for source in manifest.sources)
    assert "reddit" not in manifest.model_dump_json().lower()
```

- [ ] **Step 2: Create the manifest**

Use these exact accounts and URLs:

- `S021` FoodNavigator — `https://x.com/FoodNavigator`
- `S022` FoodNavAsia — `https://x.com/FoodNavAsia`
- `S023` just_food — `https://x.com/just_food`
- `S028` FoodSafetyMag — `https://x.com/FoodSafetyMag`
- `S029` foodsafetynews — `https://x.com/foodsafetynews`
- `S038` FDAFood — `https://x.com/FDAFood`

Each source uses `adapter: "x_official_api"`, `enabled: false`, `collection_tier: "discovery"`, `evidence_tier: 4`, and options `{"retention_mode":"metadata_only","evidence_role":"discovery_only"}`.

- [ ] **Step 3: Reject accidental unsupported activation and add the compliant adapter**

In `load_source_packs()`, after applying overrides, reject an enabled `x_official_api` source unless `FoodScopeConfig.x_access_mode == "official_api"` and `x_bearer_token_env` matches `^[A-Z][A-Z0-9_]*$`. Copy that environment-variable name into the source's runtime options without resolving its value.

Implement `XOfficialAPIAdapter` with `httpx` calls to X API v2 user lookup and recent-post endpoints. Read the bearer value from the named environment variable at request time, emit only post ID, account ID, URL, timestamp, and a bounded short clue, and never log the authorization header. Add it to `ADAPTERS` under `x_official_api`. Do not add scraping, Playwright, cookies, or third-party actor fallback to FoodScope.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/foodscope/test_x_watch_pack.py tests/foodscope/sources/test_x_official_api.py tests/foodscope/test_config_models.py -v
uv run pytest
git add data/foodscope/source_packs/x_watch.json src/foodscope/loaders.py src/foodscope/sources tests/foodscope
git commit -m "data: add disabled compliant X watch pack"
```

### Task 5: Add source health and 14-day trial reporting

**Files:**
- Create: `src/foodscope/source_health.py`
- Create: `scripts/foodscope_source_report.py`
- Test: `tests/foodscope/test_source_health.py`
- Create at trial time: `data/trials/source-trial-YYYY-MM-DD.json`
- Create at trial completion: `data/trials/source-trial-summary.md`

**Interfaces:**
- Produces: `SourceRunMetric` and `SourceTrialSummary`.
- Produces CLI report with success rate, parse rate, candidates, admitted items, commercial share, duplicate rate, unique events, sponsored share, access restrictions, and estimated AI cost.

- [ ] **Step 1: Write failing aggregation tests**

Use 14 fixed daily metric rows and assert:

```python
assert summary.fetch_success_rate == 13 / 14
assert summary.unique_valid_events == 8
assert summary.commercial_share == 0.75
assert summary.recommended_collection_tier == "core"
```

Also test that paywall/robots denial never recommends a direct-content adapter.

- [ ] **Step 2: Implement health models and report CLI**

`SourceRunMetric` contains:

```python
source_id: str
run_id: str
fetch_status: str
published_at_parse_rate: float
candidate_count: int
food_relevant_count: int
admitted_count: int
commercial_count: int
duplicate_event_count: int
unique_event_count: int
sponsored_count: int
access_mode: str
ai_tokens: int
estimated_cost: float
```

The CLI reads run manifests, aggregates per source, writes JSON and Markdown sorted by unique valid events, commercial share, and fetch stability, and recommends `core`, `extended`, `discovery`, or `disable`.

Use these deterministic recommendations over the 14-day window:

- `disable` when access mode is `robots_denied` or `terms_denied`, fetch success is below `0.50`, or unique valid events equal `0`;
- `core` when fetch success and published-date parse rate are both at least `0.90` and unique valid events are at least `5`;
- `extended` when fetch success is at least `0.70` and unique valid events are at least `2`;
- `discovery` otherwise.

Commercial and sponsored shares remain review columns and do not automatically raise evidence tier. An access-restricted source may be retained only as a metadata/query discovery definition, never as a direct-content adapter.

- [ ] **Step 3: Integrate metrics into FoodScope orchestration**

After each run, append one metric per attempted source to the run manifest. Never include credentials, article bodies, subscriber addresses, or webhook URLs.

- [ ] **Step 4: Verify tooling**

```bash
uv run pytest tests/foodscope/test_source_health.py -v
uv run python scripts/foodscope_source_report.py --runs tests/fixtures/foodscope/trial-runs --output /tmp/foodscope-source-report
test -f /tmp/foodscope-source-report/source-trial-summary.md
uv run pytest
git add src/foodscope/source_health.py scripts/foodscope_source_report.py tests/foodscope tests/fixtures/foodscope/trial-runs
git commit -m "feat: report FoodScope source trial metrics"
```

- [ ] **Step 5: Run the release trial**

Run the scheduled pipeline for 14 consecutive days. Generate `data/trials/source-trial-summary.md`, review the report against the design thresholds, apply its final `core`/`extended`/`discovery`/`disable` recommendations to the static manifests, and rerun the manifest and full test suites before committing:

```bash
uv run pytest tests/foodscope/test_source_pack_builder.py tests/foodscope/test_official_and_query_packs.py tests/foodscope/test_x_watch_pack.py -v
uv run pytest
git add data/foodscope/source_packs data/trials/source-trial-summary.md
git commit -m "data: finalize FoodScope source trial tiers"
```
