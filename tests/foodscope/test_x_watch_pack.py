import json
from pathlib import Path

import pytest

from src.foodscope.config import FoodScopeConfig, SourcePackManifest
from src.foodscope.loaders import load_source_packs
from src.foodscope.models import EvidenceTier


PACK_PATH = Path("data/foodscope/source_packs/x_watch.json")


def load_manifest() -> SourcePackManifest:
    return SourcePackManifest.model_validate(
        json.loads(PACK_PATH.read_text(encoding="utf-8"))
    )


def test_x_watch_contains_only_approved_disabled_accounts():
    manifest = load_manifest()

    assert {source.id for source in manifest.sources} == {
        "S021",
        "S022",
        "S023",
        "S028",
        "S029",
        "S038",
    }
    assert all(source.enabled is False for source in manifest.sources)
    assert all(
        source.evidence_tier == EvidenceTier.WEAK_SIGNAL
        for source in manifest.sources
    )
    assert all(
        source.options["retention_mode"] == "metadata_only"
        for source in manifest.sources
    )
    assert "reddit" not in manifest.model_dump_json().lower()


def test_disabled_x_pack_loads_without_credentials():
    sources = load_source_packs(
        FoodScopeConfig(source_packs=["x_watch"])
    )

    assert len(sources) == 6
    assert not any(source.enabled for source in sources)


def test_enabling_x_requires_explicit_official_api_mode():
    with pytest.raises(
        ValueError, match="x_access_mode.*official_api"
    ):
        load_source_packs(
            FoodScopeConfig(
                source_packs=["x_watch"],
                source_overrides={"S021": {"enabled": True}},
            )
        )


def test_enabled_x_receives_env_name_without_resolving_secret():
    sources = load_source_packs(
        FoodScopeConfig(
            source_packs=["x_watch"],
            source_overrides={"S021": {"enabled": True}},
            x_access_mode="official_api",
            x_bearer_token_env="FOODSCOPE_X_BEARER_TOKEN",
        )
    )
    enabled = next(source for source in sources if source.enabled)

    assert enabled.id == "S021"
    assert (
        enabled.options["bearer_token_env"]
        == "FOODSCOPE_X_BEARER_TOKEN"
    )
    assert "secret" not in enabled.options


def test_enabled_x_rejects_unsafe_env_variable_name():
    with pytest.raises(ValueError, match="environment variable name"):
        load_source_packs(
            FoodScopeConfig(
                source_packs=["x_watch"],
                source_overrides={"S021": {"enabled": True}},
                x_access_mode="official_api",
                x_bearer_token_env="token-value",
            )
        )
