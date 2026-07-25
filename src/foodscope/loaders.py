"""Load user-selectable FoodScope profiles and source packs."""

import json
from pathlib import Path
import re

from .config import (
    BriefProfile,
    FoodScopeConfig,
    FoodSourceSpec,
    SourcePackManifest,
)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_profile(config: FoodScopeConfig) -> BriefProfile:
    """Load a built-in or explicitly configured briefing profile."""

    path = config.profile_path or config.profile_dir / f"{config.profile}.json"
    profile = BriefProfile.model_validate(_load_json(path))
    if config.profile_path is None and profile.id != config.profile:
        raise ValueError(
            f"profile id {profile.id!r} does not match {config.profile!r}"
        )
    return profile


def load_source_packs(config: FoodScopeConfig) -> list[FoodSourceSpec]:
    """Load enabled pack definitions and merge repeated source IDs."""

    merged: dict[str, FoodSourceSpec] = {}
    for pack_id in config.source_packs:
        path = config.source_pack_dir / f"{pack_id}.json"
        manifest = SourcePackManifest.model_validate(_load_json(path))
        if manifest.id != pack_id:
            raise ValueError(
                f"source pack id {manifest.id!r} does not match {pack_id!r}"
            )
        for source in manifest.sources:
            override = config.source_overrides.get(source.id, {})
            candidate = FoodSourceSpec.model_validate(
                {**source.model_dump(), **override}
            )
            if (
                candidate.adapter == "x_official_api"
                and candidate.enabled
            ):
                if config.x_access_mode != "official_api":
                    raise ValueError(
                        "enabled x_official_api source requires "
                        "x_access_mode='official_api'"
                    )
                token_env = config.x_bearer_token_env or ""
                if not re.fullmatch(
                    r"[A-Z][A-Z0-9_]*", token_env
                ):
                    raise ValueError(
                        "x_bearer_token_env must be an uppercase "
                        "environment variable name"
                    )
                candidate = candidate.model_copy(
                    update={
                        "options": {
                            **candidate.options,
                            "bearer_token_env": token_env,
                        }
                    }
                )
            if source.id in merged:
                packs = sorted(
                    set(merged[source.id].packs + candidate.packs + [pack_id])
                )
                merged[source.id] = merged[source.id].model_copy(
                    update={"packs": packs}
                )
            else:
                merged[source.id] = candidate.model_copy(
                    update={
                        "packs": sorted(set(candidate.packs + [pack_id]))
                    }
                )
    return [merged[source_id] for source_id in sorted(merged)]
