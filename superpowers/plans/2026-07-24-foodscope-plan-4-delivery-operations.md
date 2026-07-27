# FoodScope Delivery and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render one canonical FoodScope fact snapshot into Markdown, HTML, email, Feishu, WeChat draft, and MCP outputs, then run it safely on a user-configurable schedule with resume and operational checks.

**Architecture:** `BriefFacts` is the immutable boundary between intelligence and presentation. A renderer produces Markdown and inline-styled HTML with the same fact hash; independent delivery adapters consume those outputs and record idempotent results in `FoodRunStore`. A timezone-aware scheduler invokes the same CLI path used for manual runs.

**Tech Stack:** Python 3.11+, Pydantic 2, Jinja2, croniter, zoneinfo, httpx, pytest, Docker Compose, GitHub Actions, MCP.

## Global Constraints

- Consume `SelectionResult`, `FoodRunStore`, `FoodScopeOrchestrator`, and source health interfaces from Plans 2 and 3 without renaming them.
- Use one serialized `BriefFacts` object and one SHA-256 fact hash for every output channel.
- Keep Markdown as the authoritative archive; derive HTML and channel payloads from the same facts.
- Keep Horizon's legacy Markdown, email, webhook, CLI, and MCP behavior unchanged when `foodscope.enabled` is false.
- Read SMTP, webhook, Feishu, WeChat, and AI secrets only through configured environment-variable names.
- Create WeChat drafts only; do not call mass-send or publish endpoints.
- Isolate and record each delivery result; one failed channel must not block another.
- Do not add a public website, API server, account system, external database, or visual settings interface.

---

### Task 1: Create the canonical brief facts and renderers

**Files:**
- Create: `src/foodscope/briefing.py`
- Create: `src/foodscope/rendering.py`
- Create: `src/foodscope/templates/brief.md.j2`
- Create: `src/foodscope/templates/brief.html.j2`
- Test: `tests/foodscope/test_brief_rendering.py`
- Test fixture: `tests/fixtures/foodscope/selected_brief_facts.json`
- Modify: `src/foodscope/orchestrator.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: `BriefMetadata`, `BriefFacts`, and `RenderedBrief`.
- Produces: `BriefFacts.fact_hash() -> str`.
- Produces: `FoodBriefRenderer.render(facts) -> RenderedBrief`.
- Persists: `data/runs/{run_id}/facts.json`, `brief.md`, and `brief.html`.

- [ ] **Step 1: Write failing facts and rendering tests**

Create `tests/foodscope/test_brief_rendering.py`:

```python
import json
from pathlib import Path
from src.foodscope.briefing import BriefFacts
from src.foodscope.rendering import FoodBriefRenderer


def load_facts() -> BriefFacts:
    raw = json.loads(
        Path("tests/fixtures/foodscope/selected_brief_facts.json").read_text(encoding="utf-8")
    )
    return BriefFacts.model_validate(raw)


def test_markdown_and_html_share_one_fact_hash():
    facts = load_facts()
    rendered = FoodBriefRenderer().render(facts)
    assert rendered.facts_sha256 == facts.fact_hash()
    assert rendered.facts_sha256 in rendered.markdown
    assert rendered.facts_sha256 in rendered.html
    assert "重大风险提醒" in rendered.markdown
    assert "今日必读" in rendered.markdown
    assert "仅供行业研究参考，不构成法律或合规意见" in rendered.html


def test_empty_profile_sections_are_not_rendered():
    rendered = FoodBriefRenderer().render(load_facts())
    assert "## 空栏目" not in rendered.markdown
    assert "<h2>空栏目</h2>" not in rendered.html
```

The fixture must contain one risk alert and two selected items from different categories. Include Chinese and original titles, three-sentence Chinese summaries, the six enrichment fields, market/category/tags, evidence tier, selection reason, and original/evidence links.

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/foodscope/test_brief_rendering.py -v
```

Expected: imports fail because the briefing and rendering modules do not exist.

- [ ] **Step 3: Implement the canonical fact models**

Create `src/foodscope/briefing.py`:

```python
import hashlib
import json
from datetime import datetime
from pydantic import BaseModel, Field
from src.models import ContentItem


class BriefMetadata(BaseModel):
    run_id: str
    profile_id: str
    profile_name: str
    date: str
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    fetched_count: int
    candidate_count: int
    selected_count: int
    isolated_count: int
    source_success_count: int
    source_failure_count: int


class BriefFacts(BaseModel):
    schema_version: str = "1.0"
    metadata: BriefMetadata
    risk_alerts: list[ContentItem] = Field(default_factory=list)
    must_read: list[ContentItem] = Field(default_factory=list, max_length=5)
    sections: dict[str, list[ContentItem]] = Field(default_factory=dict)
    observations: list[str] = Field(default_factory=list)

    def canonical_json(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True, by_alias=True)
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def fact_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class RenderedBrief(BaseModel):
    facts_sha256: str
    markdown: str
    html: str
```

Before hashing, construct `sections` in the eight-category enum order and sort each section by the selector's final order. Do not mutate `BriefFacts` after construction.

- [ ] **Step 4: Implement Markdown and inline-styled HTML templates**

Add `jinja2>=3.1.0` to `pyproject.toml`. `FoodBriefRenderer` loads templates through `PackageLoader("src.foodscope", "templates")`, enables autoescape for HTML, and returns `RenderedBrief`.

Both templates must render:

1. title, active profile, date, covered time window, and run statistics;
2. risk alerts;
3. no more than five must-read items;
4. non-empty profile-ordered sections;
5. observations and watch signals;
6. source/evidence links, AI disclosure, compliance disclaimer, and fact hash.

Each item renders the Chinese title, original title, three-sentence summary, what happened, China relevance, R&D significance when non-empty, opportunity, risk when non-empty, recommended action, market/category/tags, evidence tier, and original link. HTML uses only inline CSS and escapes source text and URLs.

- [ ] **Step 5: Replace the temporary renderer and persist atomically**

In `FoodScopeOrchestrator._generate_summary()`, build one `BriefFacts` from the retained `SelectionResult`, render it once, and atomically write:

```text
data/runs/{run_id}/facts.json
data/runs/{run_id}/brief.md
data/runs/{run_id}/brief.html
```

Save the fact hash and paths in `manifest.json`, then return `rendered.markdown` to the parent Horizon run loop. Use a sibling temporary file, `flush()`, `os.fsync()`, and `Path.replace()` for each output.

- [ ] **Step 6: Verify and commit**

```bash
uv lock
uv run pytest tests/foodscope/test_brief_rendering.py tests/foodscope/test_foodscope_orchestrator.py -v
uv run pytest
git add src/foodscope tests/foodscope tests/fixtures/foodscope pyproject.toml uv.lock
git commit -m "feat: render canonical FoodScope brief facts"
```

Expected: all tests pass and the fixture produces one identical fact hash in JSON, Markdown, and HTML.

### Task 2: Deliver independently to archive, email, Feishu, and WeChat draft

**Files:**
- Create: `src/foodscope/delivery.py`
- Create: `src/foodscope/feishu.py`
- Create: `src/foodscope/wechat.py`
- Modify: `src/services/email.py`
- Modify: `src/services/webhook.py`
- Modify: `src/foodscope/orchestrator.py`
- Modify: `src/foodscope/config.py`
- Test: `tests/foodscope/test_delivery.py`
- Test: `tests/foodscope/test_feishu.py`
- Test: `tests/foodscope/test_wechat.py`
- Modify: `data/config.example.json`
- Modify: `.env.example`

**Interfaces:**
- Produces: `DeliveryStatus`, `DeliveryResult`, and `FoodDeliveryManager.deliver()`.
- Produces: `build_feishu_brief_payload(facts, rendered) -> list[dict]`.
- Produces: `WeChatDraftClient.create_draft(facts, rendered) -> DeliveryResult`.
- Extends: `EmailManager.send_daily_summary(summary_md, subject, subscribers, html_body: str | None = None)` without breaking existing callers.
- Extends: `WebhookNotifier.send_payload(payload: dict) -> WebhookDeliveryResult` without breaking existing callers.

- [ ] **Step 1: Write failing independent-delivery tests**

```python
async def test_one_failed_channel_does_not_block_others(delivery_manager, rendered, facts):
    results = await delivery_manager.deliver(facts, rendered)
    by_channel = {result.channel: result.status for result in results}
    assert by_channel == {
        "archive": "success",
        "email": "failure",
        "feishu": "success",
        "wechat_draft": "success",
    }


async def test_successful_delivery_is_idempotent(delivery_manager, rendered, facts):
    first = await delivery_manager.deliver(facts, rendered)
    second = await delivery_manager.deliver(facts, rendered)
    assert successful_attempt_count(first, second, "wechat_draft") == 1
```

Use fake email, webhook, WeChat, and run-store dependencies. Assert every result contains the same `facts_sha256`.

- [ ] **Step 2: Implement delivery result and manager contracts**

Create `src/foodscope/delivery.py`:

```python
from enum import StrEnum
from pydantic import BaseModel


class DeliveryStatus(StrEnum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILURE = "failure"


class DeliveryResult(BaseModel):
    channel: str
    status: DeliveryStatus
    facts_sha256: str
    external_id: str | None = None
    detail: str | None = None
```

`FoodDeliveryManager.deliver()` checks `FoodRunStore` before each attempt, wraps synchronous SMTP work with `asyncio.to_thread()`, runs enabled channels independently with `asyncio.gather(return_exceptions=True)`, converts exceptions to failed results without secret-bearing messages, records each result, and returns results in the fixed order archive, email, Feishu, WeChat draft.

- [ ] **Step 3: Reuse Horizon email and Feishu delivery**

Extend `EmailManager.send_daily_summary()` with optional `html_body`. Existing callers omit it and retain Horizon's Markdown-to-HTML behavior; FoodScope passes the already-rendered inline HTML.

`build_feishu_brief_payload()` emits Feishu Card JSON 2.0. The first card contains the overview, risk alerts, and must-read list. Additional cards contain non-empty sections as collapsed panels. Each card includes the fact hash in a footer, preserves source links, and stays below the platform body limit by starting a new card before 25,000 Unicode code points.

Factor the existing URL/header validation and HTTP result mapping into `WebhookNotifier.send_payload()`, then use it once per FoodScope card for configured `platform: "feishu"` or `"lark"`. Stop that channel after its first failed card and record the number already delivered. Generic webhooks continue receiving the canonical Markdown summary through Horizon's existing `#{summary}` variable substitution.

- [ ] **Step 4: Implement WeChat draft creation only**

`WeChatDraftClient` performs:

1. `GET https://api.weixin.qq.com/cgi-bin/token` with `grant_type=client_credential`, app ID, and app secret;
2. `POST https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}` with one article containing title, author, digest, rendered HTML content, the first must-read item's original URL as `content_source_url`, permanent `thumb_media_id`, and comments disabled.

Read app ID and secret from `DeliveryConfig.wechat.app_id_env` and `app_secret_env`. Fail validation before a run when WeChat is enabled but either environment value or `thumb_media_id` is missing. Redact query strings and token values from errors. Do not implement or reference `/cgi-bin/message/mass/`, free-publish, or publish endpoints.

- [ ] **Step 5: Add config examples and orchestrator delivery override**

Document this exact configuration:

```json
{
  "delivery": {
    "target_minutes": 60,
    "markdown_enabled": true,
    "html_enabled": true,
    "wechat": {
      "enabled": false,
      "app_id_env": "WECHAT_APP_ID",
      "app_secret_env": "WECHAT_APP_SECRET",
      "thumb_media_id": null,
      "author": "FoodScope"
    }
  }
}
```

Keep email and Feishu in Horizon's existing top-level `email` and `webhook` blocks. Override `FoodScopeOrchestrator._deliver_summary()` to load the saved `BriefFacts` and `RenderedBrief`, invoke `FoodDeliveryManager`, and store channel results in the run manifest.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/foodscope/test_delivery.py tests/foodscope/test_feishu.py tests/foodscope/test_wechat.py tests/test_email.py tests/test_webhook.py -v
uv run pytest
git add src/foodscope src/services/email.py src/services/webhook.py tests/foodscope data/config.example.json .env.example
git commit -m "feat: deliver FoodScope briefs across configured channels"
```

Expected: a forced email failure leaves archive, Feishu, and WeChat draft successful; the legacy Horizon email tests remain green.

### Task 3: Add timezone-aware scheduling, manual windows, resume, locks, and retention

**Files:**
- Create: `src/foodscope/scheduler.py`
- Create: `src/foodscope/retention.py`
- Modify: `src/main.py`
- Modify: `src/foodscope/orchestrator.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/foodscope/test_scheduler.py`
- Test: `tests/foodscope/test_cli.py`
- Test: `tests/foodscope/test_retention.py`

**Interfaces:**
- Produces: `RunWindow`, `resolve_run_window()`, `FoodScopeScheduler`, and `RunLock`.
- Extends CLI with `--since`, `--until`, `--no-deliver`, `--resume`, `--redeliver`, `--daemon`, and `--healthcheck`.
- Produces: `RetentionPolicy.apply(runs_root, now) -> RetentionResult`.

- [ ] **Step 1: Write failing scheduling and CLI tests**

Cover these exact cases:

```python
from datetime import datetime


def test_default_schedule_is_0630_shanghai():
    schedule = FoodScopeScheduler(timezone="Asia/Shanghai", cron="30 6 * * *")
    current = datetime.fromisoformat("2026-07-24T06:29:00+08:00")
    assert schedule.next_after(current).isoformat() == "2026-07-24T06:30:00+08:00"


def test_hours_and_explicit_window_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parse_args(["--hours", "30", "--since", "2026-07-23T00:00:00+08:00", "--until", "2026-07-24T00:00:00+08:00"])


def test_resume_defaults_to_no_redelivery():
    args = parse_args(["--resume", "latest"])
    assert args.redeliver is False
```

Also test daylight-saving conversion with `Europe/London`, invalid cron text, missing `--until`, two processes contending for the same lock, and `--daemon` rejecting manual-window and resume flags.

- [ ] **Step 2: Implement window resolution and scheduler**

Add `croniter>=3.0.0` to `pyproject.toml`. Use `zoneinfo.ZoneInfo` for configured timezone validation.

```python
from datetime import datetime
from pydantic import BaseModel


class RunWindow(BaseModel):
    since: datetime
    until: datetime
```

`resolve_run_window()` follows this precedence:

1. paired `--since` and `--until`, both RFC 3339 values with explicit offsets;
2. `--hours`, ending at the current instant;
3. configured `collection.lookback_hours`, ending at the current instant.

Reject non-positive windows and windows over 720 hours. `FoodScopeScheduler` calculates the next wall-clock occurrence from `schedule.cron` in `schedule.timezone` and invokes the normal one-run function rather than duplicating pipeline logic.

- [ ] **Step 3: Add safe CLI and run lock behavior**

Keep existing `--hours` behavior for legacy Horizon. For FoodScope:

- `--since` and `--until` temporarily override the window;
- `--no-deliver` generates and archives without external delivery;
- `--resume RUN_ID` or `--resume latest` continues after the last completed stage;
- resumed runs do not redeliver unless `--redeliver` is present;
- `--daemon` runs the configured schedule continuously and cannot combine with window or resume flags.
- `--healthcheck` validates config and returns nonzero when the latest scheduled run is overdue by more than two configured schedule intervals.

Use `fcntl.flock()` on `data/state/foodscope.lock`. A second process exits with code `75` and prints the active lock's PID and start time without touching run artifacts. Release the lock in `finally`.

Extend `FoodScopeOrchestrator.run()` with keyword-only `since`, `until`, `deliver`, and `resume_run_id`. Resume loads the most recent valid stage through `FoodRunStore`, skips completed stages, and rejects profile or schema-version mismatches.

- [ ] **Step 4: Implement retention**

`RetentionPolicy` defaults to `stage_days=30` and `brief_days=180`. After a successful scheduled run:

- remove `raw.json`, `normalized.json`, `scored.json`, `filtered.json`, and `enriched.json` from run directories older than 30 days;
- retain `facts.json`, `brief.md`, `brief.html`, `manifest.json`, and delivery metadata for 180 days;
- remove an entire run directory only after every retained artifact is older than 180 days;
- never follow symlinks and never delete outside the resolved `data/runs` root.

Tests use only `tmp_path` and fixed timestamps.

- [ ] **Step 5: Verify and commit**

```bash
uv lock
uv run pytest tests/foodscope/test_scheduler.py tests/foodscope/test_cli.py tests/foodscope/test_retention.py -v
uv run pytest tests/test_main.py tests/foodscope/test_foodscope_orchestrator.py -v
uv run pytest
git add src/main.py src/foodscope tests/foodscope pyproject.toml uv.lock
git commit -m "feat: schedule and resume FoodScope runs safely"
```

Expected: timezone, CLI conflict, lock, resume, and retention tests pass; legacy `--hours` still works.

### Task 4: Expose read-safe FoodScope MCP tools and resources

**Files:**
- Modify: `src/mcp/server.py`
- Modify: `src/mcp/service.py`
- Modify: `src/mcp/horizon_adapter.py`
- Test: `tests/foodscope/test_mcp_foodscope.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Produces tool: `fs_validate_config(check_env: bool = True)`.
- Produces tool: `fs_run_pipeline(hours, since, until, profile, deliver, resume_run_id)`.
- Produces resources under `foodscope://runs` and `foodscope://latest`.

- [ ] **Step 1: Write failing MCP contract tests**

Assert registration and payloads for:

```text
foodscope://runs
foodscope://runs/{run_id}/manifest
foodscope://runs/{run_id}/stage/{stage}
foodscope://runs/{run_id}/isolated
foodscope://runs/{run_id}/brief/{format}
foodscope://latest/brief/{format}
```

Valid `stage` values are `raw`, `normalized`, `scored`, `filtered`, `enriched`, and `summary`; valid brief formats are `facts`, `markdown`, and `html`.

Assert `fs_run_pipeline` defaults to `deliver=false`, profile overrides affect only that run, and malformed run IDs or traversal strings return structured MCP errors.

- [ ] **Step 2: Implement service methods**

Extend `HorizonPipelineService` with FoodScope-aware methods that use `create_orchestrator()`, `FoodRunStore`, and safe resolved paths. Return bounded stage lists with counts and truncation flags. Return isolation entries without raw article bodies, credentials, subscriber addresses, or webhook URLs.

`fs_validate_config` validates profile files, source packs, weights, cron/timezone, enabled-channel environment names, and enabled-channel environment values only when `check_env` is true.

`fs_run_pipeline` accepts one temporary profile ID without writing `data/config.json`. It may trigger or resume a run but cannot redeliver unless its explicit `deliver` argument is true.

- [ ] **Step 3: Register tools and resources without destructive capabilities**

Register the two tools and six resource templates in `src/mcp/server.py`. Do not register tools that modify config, delete runs, upload source content, publish a WeChat draft, or send a WeChat mass message. Preserve all existing `hz_*` tools and `horizon://` resources.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/foodscope/test_mcp_foodscope.py tests/test_mcp_server.py tests/test_mcp_service.py -v
uv run pytest
git add src/mcp tests/foodscope tests/test_mcp_server.py
git commit -m "feat: expose safe FoodScope MCP resources"
```

Expected: FoodScope resources are readable, trigger defaults are non-delivering, traversal is rejected, and existing Horizon MCP tests pass.

### Task 5: Add end-to-end fixtures, deployment files, documentation, and release gates

**Files:**
- Create: `tests/foodscope/test_e2e_foodscope.py`
- Create: `tests/fixtures/foodscope/e2e/feeds/`
- Create: `tests/fixtures/foodscope/e2e/ai_responses/`
- Create: `tests/fixtures/foodscope/e2e/config.json`
- Create: `data/config.foodscope.example.json`
- Modify: `.env.example`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Create: `.github/workflows/foodscope-ci.yml`
- Create: `.github/workflows/foodscope-run.yml`
- Create: `docs/foodscope/configuration.md`
- Create: `docs/foodscope/source-packs.md`
- Create: `docs/foodscope/profiles.md`
- Create: `docs/foodscope/operations.md`
- Create: `docs/foodscope/contributing.md`
- Modify: `README.md`
- Modify: `README_zh.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: one offline end-to-end suite for all five profiles and delivery formats.
- Produces: one self-hosted Docker Compose path and one manually dispatched GitHub Actions path.
- Produces: user documentation for configuration, sources, profiles, channels, recovery, and contributions.

- [ ] **Step 1: Write the offline end-to-end test**

Use fixed English, Japanese, Korean, and Chinese source fixtures, fake AI responses, `httpx.MockTransport`, fake SMTP, fake Feishu, and fake WeChat endpoints. For each profile in `balanced`, `market`, `new_products`, `rd`, and `compliance`, run:

```text
fetch → normalize → URL/event deduplicate → analyze → evidence → select → enrich → render → deliver
```

Assert:

- all six run stages are saved;
- the expected profile changes ordering without changing evidence decisions;
- regulation and recall facts include official evidence URLs;
- the selected event set has no duplicate event keys;
- Markdown, HTML, email, Feishu, WeChat draft, and MCP return the same fact hash;
- one source, one AI item, and one channel can fail without aborting the run;
- no HTTP call reaches the public network.

- [ ] **Step 2: Create the complete open-source example**

`data/config.foodscope.example.json` must validate without modification and include:

- default `balanced` profile;
- `official_evidence`, `global_industry`, and `product_launches` packs;
- Shanghai timezone, `30 6 * * *` cron, 30-hour lookback, and 60-minute target;
- separate `ai_routes.fast` and `ai_routes.analysis` configurations produced by Plan 1;
- Markdown and HTML enabled;
- email, Feishu, WeChat draft, and X watch disabled;
- environment-variable names only.

`.env.example` lists names with empty values. Never commit a real recipient, webhook, app ID, app secret, password, bearer token, or AI key.

- [ ] **Step 3: Make Docker and GitHub Actions use the same CLI**

`docker-compose.yml` mounts `./data:/app/data`, uses `restart: unless-stopped`, and runs:

```yaml
command: ["uv", "run", "python", "-m", "src.main", "--daemon"]
```

Add:

```yaml
healthcheck:
  test: ["CMD", "uv", "run", "python", "-m", "src.main", "--healthcheck"]
  interval: 5m
  timeout: 30s
  retries: 3
```

The command validates configuration and checks that the latest scheduled run is not overdue by more than two configured schedule intervals.

Add `ruff>=0.6.0` and `mypy>=1.11.0` to the development dependency group and commit their configuration in `pyproject.toml`. `.github/workflows/foodscope-ci.yml` runs `uv sync --extra dev`, the full pytest suite, `ruff check`, and `mypy`. `.github/workflows/foodscope-run.yml` is `workflow_dispatch` only, accepts `hours` and `deliver` inputs, and invokes the same CLI; the workflow has no automatic schedule in phase one.

- [ ] **Step 4: Write operator and contributor documentation**

Document:

- every FoodScope configuration field and validation error;
- enabling, disabling, overriding, and adding source packs;
- copying and editing all five profiles;
- schedule/timezone/lookback examples;
- SMTP, Feishu, and WeChat draft setup using environment-variable names;
- manual run, no-delivery run, explicit window, daemon, resume, and explicit redelivery commands;
- run directory layout, stage meanings, fact hash, logs, metrics, retention, degraded runs, and recovery;
- X official-API-only policy and default disabled state;
- evidence rules, scoring dimensions, AI limitations, copyright/robots policy, and legal disclaimer;
- adapter, market, source-pack, taxonomy, profile, prompt, and template contribution tests.

Update both READMEs with a FoodScope quick start and links to all five documents.

- [ ] **Step 5: Run release verification**

```bash
uv run pytest tests/foodscope/test_e2e_foodscope.py -v
uv run pytest
uv run ruff check src tests scripts
uv run mypy src
docker compose config --quiet
docker build -t foodscope:test .
docker run --rm foodscope:test uv run python -m src.main --help
git diff --check
```

Expected: all configured commands exit `0`; `--help` lists `--hours`, `--since`, `--until`, `--no-deliver`, `--resume`, `--redeliver`, `--daemon`, and `--healthcheck`. Fix all imported-baseline Ruff and mypy findings before enabling the required CI checks.

- [ ] **Step 6: Commit and start the operational acceptance window**

```bash
git add src tests data .env.example Dockerfile docker-compose.yml .github docs README.md README_zh.md pyproject.toml uv.lock
git commit -m "feat: complete FoodScope delivery and operations"
```

Deploy the container with a persistent `data` volume and run the 14-day acceptance window from the design. At completion, attach `data/trials/source-trial-summary.md` and a run-level report covering schedule completion, relevance, duplicate rate, source-link validity, commercial share, profile diversity, channel success, latency, and model cost. Release only after the design thresholds pass or every exception has a documented corrective action and rerun result.
