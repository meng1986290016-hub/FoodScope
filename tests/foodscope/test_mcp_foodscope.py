from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.foodscope.briefing import BriefFacts
from src.foodscope.rendering import FoodBriefRenderer
from src.foodscope.run_store import FoodRunStore, RunStage
from src.mcp.errors import HorizonMcpError
from src.mcp.server import mcp
from src.mcp.service import HorizonPipelineService


FIXTURE = Path(
    "tests/fixtures/foodscope/selected_brief_facts.json"
)


def _prepared_service(tmp_path):
    root = tmp_path / "runs"
    store = FoodRunStore(root)
    run_id = store.create_run("balanced")
    facts = BriefFacts.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    ).model_copy(
        update={
            "metadata": BriefFacts.model_validate_json(
                FIXTURE.read_text(encoding="utf-8")
            ).metadata.model_copy(
                update={"run_id": run_id}
            )
        }
    )
    rendered = FoodBriefRenderer().render(facts)
    item = facts.must_read[0]
    for stage in (
        RunStage.RAW,
        RunStage.NORMALIZED,
        RunStage.SCORED,
        RunStage.FILTERED,
        RunStage.ENRICHED,
    ):
        store.save_stage(run_id, stage, [item])
    store.save_stage(
        run_id,
        RunStage.SUMMARY,
        {
            "language": "zh",
            "markdown": rendered.markdown,
        },
    )
    store.save_brief_artifacts(
        run_id, facts, rendered
    )
    return (
        HorizonPipelineService(
            runs_root=tmp_path / "mcp-runs",
            foodscope_runs_root=root,
        ),
        store,
        run_id,
        facts,
        rendered,
    )


def test_foodscope_read_resources_are_bounded_and_consistent(
    tmp_path,
):
    service, _, run_id, facts, rendered = _prepared_service(
        tmp_path
    )

    listed = service.fs_list_runs()
    manifest = service.fs_get_manifest(run_id)
    stage = service.fs_get_stage(
        run_id, "raw", max_items=1
    )
    isolated = service.fs_get_isolated(run_id)
    markdown = service.fs_get_brief(run_id, "markdown")
    latest_html = service.fs_get_latest_brief("html")

    assert listed["items"][0]["run_id"] == run_id
    assert manifest["manifest"]["facts_sha256"] == (
        facts.fact_hash()
    )
    assert stage["count"] == 1
    assert stage["truncated"] is False
    assert isolated == {
        "run_id": run_id,
        "count": 0,
        "items": [],
        "truncated": False,
    }
    assert markdown["facts_sha256"] == rendered.facts_sha256
    assert markdown["content"] == rendered.markdown
    assert latest_html["run_id"] == run_id
    assert latest_html["content"] == rendered.html


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("fs_get_manifest", ("../../etc",)),
        ("fs_get_stage", ("../outside", "raw")),
        ("fs_get_brief", ("nested/run", "html")),
    ],
)
def test_foodscope_resources_reject_traversal(
    tmp_path, method, args
):
    service = HorizonPipelineService(
        foodscope_runs_root=tmp_path / "runs"
    )

    with pytest.raises(
        HorizonMcpError, match="FS_INVALID_RUN_ID"
    ):
        getattr(service, method)(*args)


def test_foodscope_stage_and_format_are_allowlisted(tmp_path):
    service, _, run_id, _, _ = _prepared_service(
        tmp_path
    )

    with pytest.raises(
        HorizonMcpError, match="FS_INVALID_STAGE"
    ):
        service.fs_get_stage(run_id, "secrets")
    with pytest.raises(
        HorizonMcpError, match="FS_INVALID_FORMAT"
    ):
        service.fs_get_brief(run_id, "../../config")


def test_isolation_resource_redacts_secret_bearing_errors(
    tmp_path,
):
    root = tmp_path / "runs"
    store = FoodRunStore(root)
    run_id = store.create_run("balanced")
    facts = BriefFacts.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )
    candidate = facts.must_read[0].model_copy(deep=True)
    candidate.metadata.update(
        {
            "foodscope_isolated": True,
            "foodscope_analysis_error": (
                "request failed token=super-secret"
            ),
        }
    )
    store.save_stage(run_id, RunStage.SCORED, [candidate])
    service = HorizonPipelineService(
        foodscope_runs_root=root
    )

    payload = service.fs_get_isolated(run_id)
    rendered = json.dumps(payload)

    assert "super-secret" not in rendered
    assert "token=<redacted>" in payload["items"][0]["error"]


def test_fs_run_pipeline_defaults_to_no_delivery_and_profile_is_temporary(
    tmp_path, monkeypatch
):
    service = HorizonPipelineService(
        foodscope_runs_root=tmp_path / "runs"
    )
    config = SimpleNamespace(
        foodscope=SimpleNamespace(
            enabled=True, profile="balanced"
        )
    )
    context = SimpleNamespace(
        horizon_path=tmp_path,
        config_path=tmp_path / "config.json",
        runtime=SimpleNamespace(),
        config=config,
    )
    monkeypatch.setattr(
        service,
        "_build_foodscope_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        "src.mcp.service.make_storage",
        lambda runtime, config_path: object(),
    )
    calls = []
    store = FoodRunStore(tmp_path / "runs")

    class FakeOrchestrator:
        active_run_id = store.create_run("market")
        run_store = store

        async def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "src.mcp.service.make_orchestrator",
        lambda runtime, loaded_config, storage: (
            FakeOrchestrator()
        ),
    )

    result = asyncio.run(
        service.fs_run_pipeline(profile="market")
    )

    assert calls == [
        {
            "force_hours": 30,
            "since": None,
            "until": None,
            "deliver": False,
            "resume_run_id": None,
        }
    ]
    assert result["deliver"] is False
    assert result["profile"] == "market"
    assert config.foodscope.profile == "balanced"


def test_fs_validate_config_can_skip_environment_values(
    tmp_path, monkeypatch
):
    repo_root = Path(__file__).resolve().parents[2]
    raw = json.loads(
        (repo_root / "data/config.example.json").read_text(
            encoding="utf-8"
        )
    )
    raw["foodscope"]["enabled"] = True
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(raw), encoding="utf-8"
    )
    service = HorizonPipelineService(
        foodscope_runs_root=tmp_path / "runs"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    unchecked = asyncio.run(
        service.fs_validate_config(
            horizon_path=str(repo_root),
            config_path=str(config_path),
            check_env=False,
        )
    )
    checked = asyncio.run(
        service.fs_validate_config(
            horizon_path=str(repo_root),
            config_path=str(config_path),
            check_env=True,
        )
    )

    assert unchecked["valid"] is True
    assert unchecked["source_count"] > 0
    assert unchecked["missing_env"] == []
    assert checked["valid"] is False
    assert checked["missing_env"] == ["OPENAI_API_KEY"]


def test_foodscope_tools_and_resources_are_registered():
    tools = {
        tool.name for tool in asyncio.run(mcp.list_tools())
    }
    resources = {
        str(resource.uri)
        for resource in asyncio.run(mcp.list_resources())
    }
    templates = {
        template.uriTemplate
        for template in asyncio.run(
            mcp.list_resource_templates()
        )
    }

    assert {"fs_validate_config", "fs_run_pipeline"} <= tools
    assert "foodscope://runs" in resources
    assert {
        "foodscope://runs/{run_id}/manifest",
        "foodscope://runs/{run_id}/stage/{stage}",
        "foodscope://runs/{run_id}/isolated",
        "foodscope://runs/{run_id}/brief/{format}",
        "foodscope://latest/brief/{format}",
    } <= templates
    assert not any(
        name.startswith("fs_")
        and any(
            forbidden in name
            for forbidden in (
                "delete",
                "publish",
                "mass",
                "config_write",
            )
        )
        for name in tools
    )
