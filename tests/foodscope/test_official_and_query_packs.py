import json
from pathlib import Path

from scripts.build_foodscope_official_query_packs import (
    EXPECTED_OFFICIAL,
    EXPECTED_QUERIES,
    build_packs,
)
from src.foodscope.config import SourcePackManifest
from src.foodscope.models import CollectionTier, EvidenceTier


PACK_DIR = Path("data/foodscope/source_packs")
CATALOG = Path(
    "docs/superpowers/specs/"
    "2026-07-23-foodscope-source-catalog.md"
)


def load_manifest(pack_id: str) -> SourcePackManifest:
    return SourcePackManifest.model_validate(
        json.loads(
            (PACK_DIR / f"{pack_id}.json").read_text(
                encoding="utf-8"
            )
        )
    )


def test_official_and_query_packs_have_exact_ids():
    official = load_manifest("official_evidence")
    queries = load_manifest("discovery_queries")

    assert {source.id for source in official.sources} == (
        EXPECTED_OFFICIAL
    )
    assert {source.id for source in queries.sources} == (
        EXPECTED_QUERIES
    )


def test_official_sources_are_primary_and_queries_are_discovery():
    official = load_manifest("official_evidence")
    queries = load_manifest("discovery_queries")

    assert all(
        source.evidence_tier == EvidenceTier.PRIMARY
        for source in official.sources
    )
    assert len(queries.sources) == 20
    assert all(
        source.evidence_tier == EvidenceTier.DISCOVERY
        for source in queries.sources
    )
    assert all(
        source.collection_tier == CollectionTier.DISCOVERY
        for source in queries.sources
    )


def test_every_official_adapter_has_its_concrete_options():
    required = {
        "rss": set(),
        "json_api": {
            "items_path",
            "title_field",
            "url_field",
            "date_field",
            "content_field",
        },
        "html_list": {
            "item_selector",
            "title_selector",
            "link_selector",
            "date_selector",
        },
        "document_index": {
            "item_selector",
            "title_selector",
            "link_selector",
            "date_selector",
        },
    }

    for source in load_manifest("official_evidence").sources:
        assert source.adapter in required
        assert required[source.adapter] <= set(source.options)


def test_query_provider_policy_and_limits_are_explicit():
    queries = load_manifest("discovery_queries")
    for source in queries.sources:
        providers = source.options["providers"]
        if source.languages[0] in {"ja", "ko"}:
            assert providers == ["google_news"]
        else:
            assert providers == ["google_news", "gdelt"]
        assert source.options["max_candidates_per_provider"] == 20
        assert source.options["max_candidates_after_dedup"] == 12
        assert source.options["query"]


def test_official_query_builder_is_deterministic(tmp_path):
    build_packs(CATALOG, tmp_path)

    for filename in (
        "official_evidence.json",
        "discovery_queries.json",
    ):
        assert (tmp_path / filename).read_bytes() == (
            PACK_DIR / filename
        ).read_bytes()
