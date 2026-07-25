import json
from pathlib import Path

from scripts.build_foodscope_source_packs import (
    EXPECTED_KEEP,
    PRODUCT_LAUNCH_IDS,
    build_packs,
)
from src.foodscope.config import SourcePackManifest
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
)


PACK_DIR = Path("data/foodscope/source_packs")
SOURCE = Path(
    "docs/superpowers/specs/"
    "2026-07-23-foodscope-industry-media-longlist.md"
)
PRIMARY_PACKS = {
    "global_industry",
    "ingredients_rd",
    "packaging_processing",
    "retail_foodservice",
    "japan",
    "korea",
    "southeast_asia",
    "research_data",
}


def _load(path: Path) -> SourcePackManifest:
    return SourcePackManifest.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def test_non_social_manifests_cover_exact_keep_set():
    found = set()
    for pack_id in PRIMARY_PACKS:
        manifest = _load(PACK_DIR / f"{pack_id}.json")
        found.update(source.id for source in manifest.sources)

    assert found == EXPECTED_KEEP


def test_each_retained_source_has_one_primary_pack():
    memberships: dict[str, list[str]] = {}
    for pack_id in PRIMARY_PACKS:
        for source in _load(PACK_DIR / f"{pack_id}.json").sources:
            memberships.setdefault(source.id, []).append(pack_id)

    assert set(memberships) == EXPECTED_KEEP
    assert all(len(packs) == 1 for packs in memberships.values())


def test_generated_media_contracts_are_safe_and_runnable():
    sources = [
        source
        for pack_id in PRIMARY_PACKS
        for source in _load(PACK_DIR / f"{pack_id}.json").sources
    ]

    assert all(source.adapter == "html_list" for source in sources)
    assert all(source.enabled for source in sources)
    assert all(
        source.evidence_tier == EvidenceTier.INDUSTRY
        for source in sources
    )
    assert all(
        source.collection_tier == CollectionTier.EXTENDED
        for source in sources
    )
    assert all(source.options["item_selector"] for source in sources)
    assert all(source.categories for source in sources)
    assert "reddit" not in json.dumps(
        [source.model_dump(mode="json") for source in sources]
    ).lower()


def test_product_launch_pack_contains_exact_secondary_membership():
    manifest = _load(PACK_DIR / "product_launches.json")

    assert {source.id for source in manifest.sources} == (
        PRODUCT_LAUNCH_IDS
    )


def test_builder_is_deterministic_against_committed_manifests(tmp_path):
    build_packs(SOURCE, tmp_path)

    generated = sorted(path.name for path in tmp_path.glob("*.json"))
    assert generated == sorted(
        [f"{pack_id}.json" for pack_id in PRIMARY_PACKS]
        + ["product_launches.json"]
    )
    for filename in generated:
        assert (tmp_path / filename).read_bytes() == (
            PACK_DIR / filename
        ).read_bytes()
