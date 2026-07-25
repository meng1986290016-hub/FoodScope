#!/usr/bin/env python3
"""Aggregate FoodScope run manifests into source-trial reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.foodscope.source_health import (
    SourceRunMetric,
    SourceTrialSummary,
    summarize_metrics,
)


def load_metrics(runs_dir: Path) -> list[SourceRunMetric]:
    metrics: list[SourceRunMetric] = []
    for path in sorted(runs_dir.glob("**/manifest.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        metrics.extend(
            SourceRunMetric.model_validate(metric)
            for metric in payload.get("source_metrics", [])
        )
    return metrics


def build_report(
    runs_dir: Path, output_dir: Path
) -> list[SourceTrialSummary]:
    summaries = summarize_metrics(load_metrics(runs_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.joinpath("source-trial-summary.json").write_text(
        json.dumps(
            [
                summary.model_dump(mode="json")
                for summary in summaries
            ],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir.joinpath("source-trial-summary.md").write_text(
        _render_markdown(summaries),
        encoding="utf-8",
    )
    return summaries


def _render_markdown(
    summaries: list[SourceTrialSummary],
) -> str:
    lines = [
        "# FoodScope Source Trial Summary",
        "",
        (
            "| Source | Status | Days | Consecutive | Attempt days | Runs | Fetch | Date parse | Candidates | "
            "Admitted | Unique | Commercial | Duplicate | Sponsored | "
            "AI tokens | Cost | Access | Tier | Adapter |"
        ),
        (
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
            "---:|---:|---|---|---|"
        ),
    ]
    for summary in summaries:
        cost = (
            f"{summary.estimated_cost:.4f}"
            if summary.estimated_cost is not None
            else "unknown"
        )
        lines.append(
            f"| {summary.source_id} | {summary.trial_status} | "
            f"{summary.trial_day_count} | "
            f"{summary.consecutive_day_count} | "
            f"{summary.attempt_day_count} | "
            f"{summary.run_count} | "
            f"{summary.fetch_success_rate:.1%} | "
            f"{summary.published_at_parse_rate:.1%} | "
            f"{summary.candidate_count} | {summary.admitted_count} | "
            f"{summary.unique_valid_events} | "
            f"{summary.commercial_share:.1%} | "
            f"{summary.duplicate_rate:.1%} | "
            f"{summary.sponsored_share:.1%} | "
            f"{summary.ai_tokens} | "
            f"{cost} | "
            f"{', '.join(summary.access_modes)} | "
            f"{summary.recommended_collection_tier} | "
            f"{summary.recommended_adapter_mode} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_report(args.runs, args.output)


if __name__ == "__main__":
    main()
