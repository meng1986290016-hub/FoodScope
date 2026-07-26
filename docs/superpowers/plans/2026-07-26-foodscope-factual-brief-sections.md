# FoodScope Factual Brief Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split selected intelligence into score-based “今日必读/今日新闻” sections and render only factual event details with publisher and Beijing publication time.

**Architecture:** Persist the existing selector base rank as structured item metadata, remove the six-point admission gate from bundled profiles, and build both sections at the canonical `BriefFacts` boundary. Restrict second-pass enrichment to `what_happened_zh` plus `key_facts_zh`, then share source/date formatting across Markdown, HTML, Feishu, and WeChat-derived output.

**Tech Stack:** Python 3.12, Pydantic, Jinja2, pytest, Ruff, Mypy.

## Global Constraints

- The section boundary is the existing selector base rank: `>= 6.0` is “今日必读”; `< 6.0` is “今日新闻”.
- Evidence admission, relevance filtering, deduplication, risk override, `max_items`, `max_per_source`, profile weights, and ordering remain active.
- New AI enrichment may contain only factual event description and source-supported key facts.
- Publication timestamps render in `Asia/Shanghai`.
- Existing saved facts remain readable.

---

### Task 1: Admit and partition selected items by structured base score

**Files:**
- Modify: `src/foodscope/selector.py`
- Modify: `src/foodscope/briefing.py`
- Modify: `src/foodscope/orchestrator.py`
- Modify: `data/foodscope/profiles/*.json`
- Test: `tests/foodscope/test_selector.py`
- Test: `tests/foodscope/test_foodscope_orchestrator.py`

**Interfaces:**
- Produces: `item.metadata["foodscope_base_score"]: float`
- Produces: `BriefFacts.must_read: list[ContentItem]`
- Produces: `BriefFacts.news: list[ContentItem]`

- [ ] **Step 1: Write failing selector and orchestrator tests**

Assert that an evidence-admitted item below six is selectable when the profile floor is zero, that base score is stored as a float, and that exactly `6.0` partitions into `must_read` while `5.99` partitions into `news`.

- [ ] **Step 2: Run focused tests and verify the new assertions fail**

Run: `pytest -q tests/foodscope/test_selector.py tests/foodscope/test_foodscope_orchestrator.py`

- [ ] **Step 3: Implement structured score persistence and partitioning**

Save `candidate.base_rank` into item metadata in the selector, add `news` to `BriefFacts`, partition selected and risk items once by the structured score, and set bundled profile `minimum_score` values to `0.0`.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/foodscope/test_selector.py tests/foodscope/test_foodscope_orchestrator.py`

### Task 2: Replace interpretive enrichment with factual fields

**Files:**
- Modify: `src/foodscope/models.py`
- Modify: `src/foodscope/enricher.py`
- Modify: `src/foodscope/prompts.py`
- Modify: `tests/fixtures/foodscope/enrichment_response.json`
- Modify: `tests/fixtures/foodscope/e2e/ai_responses/enrichment.json`
- Test: `tests/foodscope/test_food_enricher.py`

**Interfaces:**
- Produces: `FoodIntelligence.key_facts_zh: list[str]`
- Consumes AI JSON: `{"what_happened_zh": str, "key_facts_zh": list[str]}`

- [ ] **Step 1: Write failing enrichment tests**

Assert that the two-field response populates `what_happened_zh` and `key_facts_zh`, and that all legacy interpretive fields are empty after applying a new result.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `pytest -q tests/foodscope/test_food_enricher.py`

- [ ] **Step 3: Implement the two-field schema and factual prompt**

Add `key_facts_zh`, accept only the two factual response fields, explicitly prohibit inference, and clear legacy fields when applying the result.

- [ ] **Step 4: Run the focused test**

Run: `pytest -q tests/foodscope/test_food_enricher.py`

### Task 3: Render two factual sections with publisher and Beijing time

**Files:**
- Modify: `src/foodscope/rendering.py`
- Modify: `src/foodscope/templates/brief.md.j2`
- Modify: `src/foodscope/templates/brief.html.j2`
- Modify: `src/foodscope/feishu.py`
- Modify: `tests/fixtures/foodscope/selected_brief_facts.json`
- Test: `tests/foodscope/test_brief_rendering.py`
- Test: `tests/foodscope/test_feishu.py`

**Interfaces:**
- Produces Jinja filter: `source_label(ContentItem) -> str`
- Produces Jinja filter: `published_beijing(datetime) -> str`

- [ ] **Step 1: Write failing output tests**

Assert both headings, the six-point boundary, source name/link, Beijing time, factual key bullets, and absence of “三句摘要/对中国企业的意义/研发意义/机会信号/风险信号/建议动作/证据”.

- [ ] **Step 2: Run focused render tests and verify failure**

Run: `pytest -q tests/foodscope/test_brief_rendering.py tests/foodscope/test_feishu.py`

- [ ] **Step 3: Implement shared source/date helpers and factual templates**

Render `must_read` and `news` exactly once, format publisher names from discovery/direct metadata with domain fallback, format dates in `Asia/Shanghai`, and align Feishu detail text.

- [ ] **Step 4: Run focused render tests**

Run: `pytest -q tests/foodscope/test_brief_rendering.py tests/foodscope/test_feishu.py`

### Task 4: Update fixtures, documentation, and verify the full pipeline

**Files:**
- Modify: `docs/foodscope/profiles.md`
- Modify: `docs/foodscope/operations.md`
- Modify: `README.md`
- Modify: affected FoodScope fixtures and snapshot expectations

**Interfaces:**
- Consumes all interfaces from Tasks 1–3.

- [ ] **Step 1: Update user documentation and compatible fixtures**

Document the zero admission floor, score-based brief sections, factual-only content, and source/date display. Migrate fixtures without deleting legacy compatibility coverage.

- [ ] **Step 2: Run all tests**

Run: `pytest -q`

- [ ] **Step 3: Run static checks**

Run: `ruff check src tests`

Run: `mypy src`

Run: `git diff --check`

- [ ] **Step 4: Inspect one rendered fixture brief**

Render the canonical fixture and verify the Markdown and HTML contain identical item membership, publisher links, dates, and factual fields.
