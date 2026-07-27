# FoodScope Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import a pinned Horizon baseline and add backward-compatible FoodScope configuration, dual AI routes, models, profiles, pack loading, and orchestrator construction.

**Architecture:** Keep Horizon's `src` package at repository root and add all food-domain code below `src/foodscope/`. Root models receive only optional FoodScope fields, while existing Horizon configurations continue to validate and run unchanged.

**Tech Stack:** Python 3.11+, uv, Pydantic 2, pytest, Git, JSON.

## Global Constraints

- Pin upstream Horizon to `1e2fdc7ccb177f33c59aef2082c4093e1e82b22c`.
- Preserve MIT license and upstream attribution.
- Keep `data/config.json` authoritative; examples and built-ins are public JSON.
- Use environment-variable names, never literal secrets.
- Keep all upstream tests passing.

---

### Task 1: Import the pinned Horizon baseline

**Files:**
- Create from upstream: `src/`, `tests/`, `scripts/`, `data/config.example.json`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, `LICENSE`, `README.md`, `README_zh.md`
- Create: `UPSTREAM.md`
- Preserve: `docs/superpowers/`

**Interfaces:**
- Consumes: clean FoodScope documentation repository at commit `d8176c2`.
- Produces: importable `src` package and the unchanged upstream pytest suite.

- [ ] **Step 1: Create an isolated worktree**

Run the `superpowers:using-git-worktrees` skill, create branch `codex/foodscope-foundation`, and verify:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 2: Add and fetch the pinned upstream**

```bash
git remote add upstream https://github.com/Thysrael/Horizon.git
git fetch upstream 1e2fdc7ccb177f33c59aef2082c4093e1e82b22c
git merge --allow-unrelated-histories --no-commit 1e2fdc7ccb177f33c59aef2082c4093e1e82b22c
```

Expected: merge is staged or working-tree merged, and `docs/superpowers/` remains present.

- [ ] **Step 3: Record provenance**

Create `UPSTREAM.md` with:

```markdown
# Upstream Horizon

- Repository: https://github.com/Thysrael/Horizon
- Initial imported commit: `1e2fdc7ccb177f33c59aef2082c4093e1e82b22c`
- License: MIT
- Sync policy: fetch `upstream/main`, review changes, then merge only after the Horizon and FoodScope test suites pass.

FoodScope preserves Horizon's copyright and license notices. FoodScope-specific source packs, prompts, schemas, profiles, and templates live under `src/foodscope/` and `data/foodscope/`.
```

- [ ] **Step 4: Install and verify the unmodified baseline**

```bash
uv sync --extra dev
uv run pytest
```

Expected: all upstream tests pass with zero failures.

- [ ] **Step 5: Commit the baseline**

```bash
git add .
git commit -m "chore: import pinned Horizon baseline"
```

### Task 2: Add FoodScope domain and configuration models

**Files:**
- Create: `src/foodscope/__init__.py`
- Create: `src/foodscope/models.py`
- Create: `src/foodscope/config.py`
- Modify: `src/models.py`
- Test: `tests/foodscope/test_config_models.py`
- Test: `tests/foodscope/test_domain_models.py`

**Interfaces:**
- Consumes: Horizon `ContentItem`, `AIConfig`, and `Config`.
- Produces: `FoodIntelligence`, `ProductLaunchDetails`, `FoodSourceSpec`, `BriefProfile`, `FoodScopeConfig`, `AIRoutesConfig`, and optional `Config.foodscope`.

- [ ] **Step 1: Write failing model tests**

Create `tests/foodscope/test_domain_models.py`:

```python
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    FoodIntelligence,
    ProductLaunchDetails,
    RiskLevel,
)


def test_product_launch_analysis_is_structured():
    food = FoodIntelligence(
        category=FoodCategory.PRODUCT_INNOVATION,
        markets=["JP"],
        importance_score=8.0,
        profile_relevance_score=9.0,
        opportunity_score=7.5,
        evidence_quality_score=8.5,
        risk_level=RiskLevel.LOW,
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        product_launch=ProductLaunchDetails(
            brand="Example",
            product_name="Protein Tea",
            launch_markets=["JP"],
            launch_type="new_product",
        ),
    )
    assert food.category == FoodCategory.PRODUCT_INNOVATION
    assert food.product_launch.product_name == "Protein Tea"
```

Create `tests/foodscope/test_config_models.py`:

```python
import pytest
from src.models import Config


def legacy_config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "provider": "openai",
            "model": "gpt-4",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {"hackernews": {"enabled": False}, "reddit": {"enabled": False}, "telegram": {"enabled": False}},
        "filtering": {"ai_score_threshold": 6.0},
    }


def test_legacy_horizon_config_remains_valid():
    config = Config.model_validate(legacy_config())
    assert config.foodscope is None


def test_foodscope_defaults_to_balanced_profile():
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True}
    raw["ai_routes"] = {"fast": raw["ai"], "analysis": raw["ai"]}
    config = Config.model_validate(raw)
    assert config.foodscope.profile == "balanced"
    assert config.schedule.timezone == "Asia/Shanghai"
    assert config.collection.lookback_hours == 30
    assert config.delivery.target_minutes == 60


def test_foodscope_requires_fast_and_analysis_routes():
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True}
    with pytest.raises(ValueError, match="ai_routes"):
        Config.model_validate(raw)
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
uv run pytest tests/foodscope/test_domain_models.py tests/foodscope/test_config_models.py -v
```

Expected: collection fails because `src.foodscope` does not exist.

- [ ] **Step 3: Implement domain models**

Create `src/foodscope/models.py` with these public models and exact enum values:

```python
from enum import IntEnum, StrEnum
from typing import Optional
from pydantic import BaseModel, Field


class FoodCategory(StrEnum):
    PRODUCT_INNOVATION = "product_innovation"
    INGREDIENTS_TECHNOLOGY = "ingredients_technology"
    PACKAGING_LABELING = "packaging_labeling"
    CONSUMER_TRENDS = "consumer_trends"
    REGULATIONS_STANDARDS = "regulations_standards"
    FOOD_SAFETY_RECALLS = "food_safety_recalls"
    RETAIL_FOODSERVICE = "retail_foodservice"
    COMPANY_UPDATES = "company_updates"


class EvidenceTier(IntEnum):
    PRIMARY = 1
    INDUSTRY = 2
    DISCOVERY = 3
    WEAK_SIGNAL = 4


class CollectionTier(StrEnum):
    CORE = "core"
    EXTENDED = "extended"
    DISCOVERY = "discovery"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SEVERE = "severe"


class ProductLaunchDetails(BaseModel):
    brand: Optional[str] = None
    company: Optional[str] = None
    product_name: str
    launch_markets: list[str] = Field(default_factory=list)
    launch_date: Optional[str] = None
    audience: list[str] = Field(default_factory=list)
    ingredients: list[str] = Field(default_factory=list)
    flavors: list[str] = Field(default_factory=list)
    format: Optional[str] = None
    claims: list[str] = Field(default_factory=list)
    package_size: Optional[str] = None
    price: Optional[str] = None
    channels: list[str] = Field(default_factory=list)
    launch_type: str


class FoodIntelligence(BaseModel):
    category: FoodCategory
    markets: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    ingredient_tags: list[str] = Field(default_factory=list)
    technology_tags: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    importance_score: float = Field(ge=0, le=10)
    profile_relevance_score: float = Field(ge=0, le=10)
    opportunity_score: float = Field(ge=0, le=10)
    evidence_quality_score: float = Field(ge=0, le=10)
    risk_level: RiskLevel
    risk_reason: str = ""
    what_happened_zh: str = ""
    why_it_matters_zh: str = ""
    rd_significance_zh: str = ""
    opportunity_signal_zh: str = ""
    risk_signal_zh: str = ""
    recommended_action_zh: str = ""
    evidence_tier: EvidenceTier
    collection_tier: CollectionTier
    source_id: str = ""
    source_pack_ids: list[str] = Field(default_factory=list)
    event_key: Optional[str] = None
    original_source_url: Optional[str] = None
    evidence_urls: list[str] = Field(default_factory=list)
    official_evidence_urls: list[str] = Field(default_factory=list)
    sponsored: bool = False
    press_release: bool = False
    selection_reason: str = ""
    product_launch: Optional[ProductLaunchDetails] = None
```

- [ ] **Step 4: Implement configuration models and root compatibility**

Create `src/foodscope/config.py` defining:

```python
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from .models import CollectionTier, EvidenceTier, FoodCategory, RiskLevel


class ScheduleConfig(BaseModel):
    timezone: str = "Asia/Shanghai"
    cron: str = "30 6 * * *"


class CollectionConfig(BaseModel):
    lookback_hours: int = Field(default=30, gt=0, le=720)


class WeChatDraftConfig(BaseModel):
    enabled: bool = False
    app_id_env: str = "WECHAT_APP_ID"
    app_secret_env: str = "WECHAT_APP_SECRET"
    thumb_media_id: Optional[str] = None
    author: str = "FoodScope"


class DeliveryConfig(BaseModel):
    target_minutes: int = Field(default=60, gt=0)
    markdown_enabled: bool = True
    html_enabled: bool = True
    wechat: WeChatDraftConfig = Field(default_factory=WeChatDraftConfig)


class FoodSourceSpec(BaseModel):
    id: str
    name: str
    url: str
    adapter: str
    enabled: bool = True
    evidence_tier: EvidenceTier
    collection_tier: CollectionTier
    packs: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    categories: list[FoodCategory] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class SourcePackManifest(BaseModel):
    id: str
    name: str
    sources: list[FoodSourceSpec]


class BriefProfile(BaseModel):
    id: str
    name: str
    max_items: int = Field(default=20, ge=15, le=25)
    max_per_source: int = Field(default=3, gt=0)
    exploration_slots: int = Field(default=2, ge=0)
    commercial_min_ratio: float = Field(default=0.0, ge=0, le=1)
    minimum_score: float = Field(default=6.0, ge=0, le=10)
    risk_override_min: RiskLevel = RiskLevel.HIGH
    topic_weights: dict[FoodCategory, float]
    market_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("topic_weights")
    @classmethod
    def weights_sum_to_one(cls, value: dict[FoodCategory, float]):
        if abs(sum(value.values()) - 1.0) > 0.0001:
            raise ValueError("topic_weights must sum to 1.0")
        return value


class FoodScopeConfig(BaseModel):
    enabled: bool = False
    profile: str = "balanced"
    profile_path: Optional[Path] = None
    source_packs: list[str] = Field(default_factory=lambda: ["official_evidence", "global_industry", "product_launches"])
    source_pack_dir: Path = Path("data/foodscope/source_packs")
    profile_dir: Path = Path("data/foodscope/profiles")
    source_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    x_access_mode: Optional[Literal["official_api"]] = None
    x_bearer_token_env: Optional[str] = None
```

Modify `src/models.py`. Define these models immediately after `AIConfig`:

```python
class AIRouteConfig(AIConfig):
    concurrency: int = Field(default=4, gt=0, le=64)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)


class AIRoutesConfig(BaseModel):
    fast: AIRouteConfig
    analysis: AIRouteConfig
```

Then add the FoodScope imports and fields:

```python
from .foodscope.config import CollectionConfig, DeliveryConfig, FoodScopeConfig, ScheduleConfig
from .foodscope.models import FoodIntelligence
```

Add `FOOD = "food"` to `SourceType`, add `food: Optional[FoodIntelligence] = None` to `ContentItem`, and add these fields to `Config`:

```python
foodscope: Optional[FoodScopeConfig] = None
ai_routes: Optional[AIRoutesConfig] = None
schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
collection: CollectionConfig = Field(default_factory=CollectionConfig)
delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
```

Import `model_validator` from Pydantic and add:

```python
@model_validator(mode="after")
def validate_foodscope_ai_routes(self):
    if self.foodscope and self.foodscope.enabled and self.ai_routes is None:
        raise ValueError("ai_routes.fast and ai_routes.analysis are required when FoodScope is enabled")
    return self
```

Legacy Horizon configurations with FoodScope absent or disabled remain valid with only the existing `ai` field.

- [ ] **Step 5: Run focused and full tests**

```bash
uv run pytest tests/foodscope/test_domain_models.py tests/foodscope/test_config_models.py -v
uv run pytest
```

Expected: both commands pass with zero failures.

- [ ] **Step 6: Commit**

```bash
git add src/foodscope src/models.py tests/foodscope
git commit -m "feat: add FoodScope domain configuration"
```

### Task 3: Add profile and source-pack loaders

**Files:**
- Create: `src/foodscope/loaders.py`
- Create: `data/foodscope/profiles/balanced.json`
- Create: `data/foodscope/profiles/market.json`
- Create: `data/foodscope/profiles/new_products.json`
- Create: `data/foodscope/profiles/rd.json`
- Create: `data/foodscope/profiles/compliance.json`
- Create: `data/foodscope/source_packs/.gitkeep`
- Test: `tests/foodscope/test_loaders.py`

**Interfaces:**
- Produces: `load_profile(config: FoodScopeConfig) -> BriefProfile`
- Produces: `load_source_packs(config: FoodScopeConfig) -> list[FoodSourceSpec]`

- [ ] **Step 1: Write failing loader tests**

```python
from pathlib import Path
from src.foodscope.config import FoodScopeConfig
from src.foodscope.loaders import load_profile, load_source_packs


def test_all_builtin_profiles_validate():
    root = Path("data/foodscope/profiles")
    for profile_id in ("balanced", "market", "new_products", "rd", "compliance"):
        profile = load_profile(FoodScopeConfig(profile=profile_id, profile_dir=root))
        assert profile.id == profile_id
        assert abs(sum(profile.topic_weights.values()) - 1.0) < 0.0001


def test_duplicate_sources_from_multiple_packs_are_merged(tmp_path):
    pack = '{"id":"one","name":"One","sources":[{"id":"M001","name":"FoodNavigator","url":"https://example.com","adapter":"rss","evidence_tier":2,"collection_tier":"core","packs":["one"],"categories":["product_innovation"]}]}'
    (tmp_path / "one.json").write_text(pack, encoding="utf-8")
    (tmp_path / "two.json").write_text(pack.replace('"one"', '"two"'), encoding="utf-8")
    config = FoodScopeConfig(source_packs=["one", "two"], source_pack_dir=tmp_path)
    sources = load_source_packs(config)
    assert [source.id for source in sources] == ["M001"]
    assert sources[0].packs == ["one", "two"]
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_loaders.py -v
```

Expected: import fails because `src.foodscope.loaders` does not exist.

- [ ] **Step 3: Create the five profile JSON files**

Use the shared fields `max_items: 20`, `max_per_source: 3`, `exploration_slots: 2`, `minimum_score: 6.0`, and `risk_override_min: "high"`. Set `commercial_min_ratio` to `0.70` for `balanced` and `0.0` for the other profiles. Use these exact category weights:

| Profile | product | ingredients | packaging | consumer | regulations | safety | retail | company |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| balanced | .20 | .20 | .10 | .15 | .08 | .07 | .10 | .10 |
| market | .15 | .08 | .05 | .25 | .04 | .03 | .20 | .20 |
| new_products | .55 | .15 | .10 | .10 | .01 | .01 | .05 | .03 |
| rd | .25 | .35 | .15 | .05 | .08 | .05 | .03 | .04 |
| compliance | .03 | .05 | .10 | .01 | .40 | .35 | .01 | .05 |

Each JSON uses the enum keys from `FoodCategory`, for example:

```json
{
  "id": "balanced",
  "name": "综合情报",
  "max_items": 20,
  "max_per_source": 3,
  "exploration_slots": 2,
  "commercial_min_ratio": 0.7,
  "minimum_score": 6.0,
  "risk_override_min": "high",
  "topic_weights": {
    "product_innovation": 0.2,
    "ingredients_technology": 0.2,
    "packaging_labeling": 0.1,
    "consumer_trends": 0.15,
    "regulations_standards": 0.08,
    "food_safety_recalls": 0.07,
    "retail_foodservice": 0.1,
    "company_updates": 0.1
  },
  "market_weights": {}
}
```

- [ ] **Step 4: Implement loaders**

Create `src/foodscope/loaders.py` with:

```python
import json
from pathlib import Path
from .config import BriefProfile, FoodScopeConfig, FoodSourceSpec, SourcePackManifest


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_profile(config: FoodScopeConfig) -> BriefProfile:
    path = config.profile_path or config.profile_dir / f"{config.profile}.json"
    profile = BriefProfile.model_validate(_load_json(path))
    if config.profile_path is None and profile.id != config.profile:
        raise ValueError(f"profile id {profile.id!r} does not match {config.profile!r}")
    return profile


def load_source_packs(config: FoodScopeConfig) -> list[FoodSourceSpec]:
    merged: dict[str, FoodSourceSpec] = {}
    for pack_id in config.source_packs:
        path = config.source_pack_dir / f"{pack_id}.json"
        manifest = SourcePackManifest.model_validate(_load_json(path))
        if manifest.id != pack_id:
            raise ValueError(f"source pack id {manifest.id!r} does not match {pack_id!r}")
        for source in manifest.sources:
            override = config.source_overrides.get(source.id, {})
            candidate = source.model_copy(update=override)
            if source.id in merged:
                packs = sorted(set(merged[source.id].packs + candidate.packs + [pack_id]))
                merged[source.id] = merged[source.id].model_copy(update={"packs": packs})
            else:
                merged[source.id] = candidate.model_copy(update={"packs": sorted(set(candidate.packs + [pack_id]))})
    return [merged[source_id] for source_id in sorted(merged)]
```

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests/foodscope/test_loaders.py -v
uv run pytest
git add src/foodscope/loaders.py data/foodscope tests/foodscope/test_loaders.py
git commit -m "feat: add FoodScope profiles and pack loading"
```

Expected: both test commands pass.

### Task 4: Centralize orchestrator construction

**Files:**
- Create: `src/foodscope/orchestrator.py`
- Create: `src/orchestrator_factory.py`
- Modify: `src/main.py`
- Modify: `src/mcp/horizon_adapter.py`
- Modify: `src/setup/presets.py`
- Test: `tests/foodscope/test_orchestrator_factory.py`
- Modify: `data/config.example.json`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_zh.md`

**Interfaces:**
- Produces: `create_orchestrator(config: Config, storage: StorageManager) -> HorizonOrchestrator`
- Produces: pass-through `FoodScopeOrchestrator` ready for Plan 2 overrides.

- [ ] **Step 1: Write failing factory tests**

```python
from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.orchestrator import HorizonOrchestrator
from src.orchestrator_factory import create_orchestrator
from src.storage.manager import StorageManager
from tests.foodscope.test_config_models import legacy_config
from src.models import Config


def test_factory_preserves_legacy_horizon(tmp_path):
    config = Config.model_validate(legacy_config())
    assert type(create_orchestrator(config, StorageManager(str(tmp_path)))) is HorizonOrchestrator


def test_factory_selects_foodscope(tmp_path):
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True}
    raw["ai_routes"] = {"fast": raw["ai"], "analysis": raw["ai"]}
    config = Config.model_validate(raw)
    assert isinstance(create_orchestrator(config, StorageManager(str(tmp_path))), FoodScopeOrchestrator)
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_orchestrator_factory.py -v
```

Expected: import fails because the factory does not exist.

- [ ] **Step 3: Implement the pass-through subclass and factory**

Create `src/foodscope/orchestrator.py`:

```python
from ..orchestrator import HorizonOrchestrator


class FoodScopeOrchestrator(HorizonOrchestrator):
    """Food industry workflow; stage overrides are added in Plan 2."""
```

Create `src/orchestrator_factory.py`:

```python
from .models import Config
from .orchestrator import HorizonOrchestrator
from .storage.manager import StorageManager


def create_orchestrator(config: Config, storage: StorageManager) -> HorizonOrchestrator:
    if config.foodscope and config.foodscope.enabled:
        from .foodscope.orchestrator import FoodScopeOrchestrator
        return FoodScopeOrchestrator(config, storage)
    return HorizonOrchestrator(config, storage)
```

Replace direct `HorizonOrchestrator(config, storage)` construction in `src/main.py` and `src/mcp/horizon_adapter.py` with `create_orchestrator(config, storage)`.

- [ ] **Step 4: Extend presets and examples**

Add a FoodScope preset to `src/setup/presets.py` that writes:

```python
{
    "ai_routes": {
        "fast": selected_ai_config,
        "analysis": selected_ai_config,
    },
    "foodscope": {
        "enabled": True,
        "profile": "balanced",
        "source_packs": ["official_evidence", "global_industry", "product_launches"],
    },
    "schedule": {"timezone": "Asia/Shanghai", "cron": "30 6 * * *"},
    "collection": {"lookback_hours": 30},
    "delivery": {"target_minutes": 60, "markdown_enabled": True, "html_enabled": True},
}
```

Update examples and README files to explain that FoodScope is self-hosted, defaults to `balanced`, and requires only environment-variable names in committed JSON.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/foodscope/test_orchestrator_factory.py tests/test_mcp_adapter.py tests/test_setup_wizard.py -v
uv run pytest
git add src data .env.example README.md README_zh.md tests
git commit -m "feat: route Horizon through FoodScope extension factory"
```

Expected: all tests pass and legacy Horizon behavior remains unchanged.
