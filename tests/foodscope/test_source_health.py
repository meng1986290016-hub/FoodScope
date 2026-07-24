import json

from scripts.foodscope_source_report import build_report
from src.foodscope.source_health import (
    SourceRunMetric,
    SourceTrialSummary,
)


def metric(
    day: int,
    *,
    fetch_status: str = "success",
    parse_rate: float = 1.0,
    admitted: int = 0,
    commercial: int = 0,
    unique: int = 0,
    access_mode: str = "direct_metadata",
) -> SourceRunMetric:
    return SourceRunMetric(
        source_id="M001",
        run_id=f"run-{day:02d}",
        fetch_status=fetch_status,
        published_at_parse_rate=parse_rate,
        candidate_count=1,
        food_relevant_count=1,
        admitted_count=admitted,
        commercial_count=commercial,
        duplicate_event_count=0,
        unique_event_count=unique,
        sponsored_count=0,
        access_mode=access_mode,
        ai_tokens=100,
        estimated_cost=0.01,
    )


def test_fourteen_day_summary_applies_deterministic_tier_rules():
    rows = [
        metric(
            day,
            fetch_status="failure" if day == 14 else "success",
            parse_rate=0 if day == 14 else 1,
            admitted=1 if day <= 8 else 0,
            commercial=1 if day <= 6 else 0,
            unique=1 if day <= 8 else 0,
        )
        for day in range(1, 15)
    ]

    summary = SourceTrialSummary.from_metrics(rows)

    assert summary.fetch_success_rate == 13 / 14
    assert summary.unique_valid_events == 8
    assert summary.commercial_share == 0.75
    assert summary.recommended_collection_tier == "core"


def test_denied_or_paywalled_access_never_recommends_direct_content():
    denied = SourceTrialSummary.from_metrics(
        [
            metric(
                day,
                admitted=1,
                commercial=1,
                unique=1,
                access_mode="robots_denied",
            )
            for day in range(1, 15)
        ]
    )
    paywalled = SourceTrialSummary.from_metrics(
        [
            metric(
                day,
                admitted=1,
                commercial=1,
                unique=1,
                access_mode="paywall",
            )
            for day in range(1, 15)
        ]
    )

    assert denied.recommended_collection_tier == "disable"
    assert denied.recommended_adapter_mode == "disabled"
    assert paywalled.recommended_adapter_mode == "metadata_or_query"


def test_report_cli_builds_sorted_json_and_markdown(tmp_path):
    runs = tmp_path / "runs"
    run_dir = runs / "run-one"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "source_metrics": [
                    metric(
                        1, admitted=1, commercial=1, unique=1
                    ).model_dump(mode="json")
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    summaries = build_report(runs, output)

    assert summaries[0].source_id == "M001"
    assert (
        output / "source-trial-summary.json"
    ).is_file()
    markdown = (
        output / "source-trial-summary.md"
    ).read_text(encoding="utf-8")
    assert "M001" in markdown
    assert "AI tokens" in markdown
