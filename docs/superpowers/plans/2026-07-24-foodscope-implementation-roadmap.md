# FoodScope Horizon Industry Edition Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the open-source, self-hosted FoodScope Horizon industry edition in four independently testable milestones.

**Architecture:** Pin Horizon commit `1e2fdc7ccb177f33c59aef2082c4093e1e82b22c`, preserve its CLI and fetch → deduplicate → score/filter → enrich → summarize → deliver loop, and add an isolated `src/foodscope/` package. Each milestone leaves the repository runnable and keeps the upstream Horizon test suite green.

**Tech Stack:** Python 3.11+, uv, Pydantic 2, httpx, feedparser, BeautifulSoup, pytest, Docker, Markdown, MCP.

## Global Constraints

- Preserve Horizon's MIT license, copyright notice, and an `upstream` remote pinned initially to `1e2fdc7ccb177f33c59aef2082c4093e1e82b22c`.
- Keep `data/config.json` as the only authoritative non-secret configuration.
- Read AI, SMTP, Feishu, WeChat, and webhook secrets only from environment variables.
- Default schedule: timezone `Asia/Shanghai`, cron `30 6 * * *`, lookback `30` hours, target delivery `60` minutes.
- FoodScope requires `ai_routes.fast` for candidate analysis and `ai_routes.analysis` for selected-item enrichment.
- First run uses profile `balanced`; one profile is active per run.
- Built-in profiles are `balanced`, `market`, `new_products`, `rd`, and `compliance`.
- FoodScope source packs and example configuration contain no Reddit sources; retained X sources stay disabled by default.
- Regulations, standards, recalls, and food-safety claims require official evidence.
- Default briefing length is 15–25 items; the balanced profile targets at least 70% commercial and technical items when enough qualified candidates exist.
- Do not build a public website, external database, user accounts, multi-tenancy, payments, search, bookmarks, or a visual settings interface in phase one.
- Every behavioral change follows red-green-refactor TDD and ends with the focused tests plus `uv run pytest`.

---

## Milestone Order

1. [Foundation and extension contracts](2026-07-24-foodscope-plan-1-foundation.md)
   Import the pinned Horizon baseline, add backward-compatible FoodScope models/configuration, install five profiles, and route CLI/MCP construction through one orchestrator factory.
2. [Food intelligence pipeline](2026-07-24-foodscope-plan-2-intelligence-pipeline.md)
   Add normalization, cross-language event identity, structured AI analysis, evidence gates, profile selection, staged run storage, and FoodScope orchestration.
3. [Source packs and trial instrumentation](2026-07-24-foodscope-plan-3-source-packs.md)
   Add generic source adapters, generate the curated source-pack manifests, keep X disabled, and produce source-health and 14-day trial reports.
4. [Briefing delivery and operations](2026-07-24-foodscope-plan-4-delivery-operations.md)
   Add profile-aware Markdown/HTML, WeChat drafts, scheduling and resume CLI options, MCP resources, full documentation, and end-to-end release checks.

## Dependency Contract

- Plan 2 consumes `FoodIntelligence`, `BriefProfile`, `FoodSourceSpec`, `FoodScopeConfig`, `AIRoutesConfig`, `load_profile()`, and `load_source_packs()` from Plan 1.
- Plan 3 produces `FoodSourceRegistry.fetch()` and static pack manifests consumed by `FoodScopeOrchestrator` from Plan 2.
- Plan 4 consumes `DeliveryConfig` from Plan 1; `SelectionResult`, `FoodRunStore`, and `FoodScopeOrchestrator` from Plan 2; plus source reports from Plan 3.
- No later plan may rename an earlier public interface without updating all dependent plans and their tests in the same commit.

## Milestone Release Gates

- Foundation: upstream Horizon tests pass unchanged; legacy Horizon config still creates `HorizonOrchestrator`; FoodScope example config creates `FoodScopeOrchestrator`.
- Intelligence: fixed Chinese, English, Japanese, and Korean fixtures complete normalization → event merge → analysis → evidence → profile selection with deterministic results.
- Sources: every retained `M` decision appears in at least one manifest, exactly six retained X accounts appear disabled in `x_watch`, and no Reddit candidate appears.
- Delivery: the same selected fact objects render consistently to Markdown, HTML, email/webhook payloads, WeChat draft payloads, and MCP resources; Docker and CLI smoke tests pass.
