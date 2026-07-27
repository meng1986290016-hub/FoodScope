import json
from pathlib import Path
from urllib.parse import urlsplit

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
VERIFIED_OFFICIAL_FEEDS = {
    "M075": "https://news.nissyoku.co.jp/archives/news-cat/001/feed",
    "M076": "https://shokuhin.net/feed/",
    "M080": "https://diamond-rm.net/feed/",
    "M084": "https://www.kenko-media.com/health_idst/feed",
    "M086": "https://gekiryu-online.jp/feed",
    "M089": "https://www.foodnews.co.kr/rss/allArticle.xml",
    "M090": "https://cdn.thinkfood.co.kr/rss/gn_rss_allArticle.xml",
    "M091": "https://foodicon.co.kr/rss/allArticle.xml",
    "M092": "https://www.foodtoday.or.kr/data/rss/news.xml",
    "M093": "https://www.foodbank.co.kr/rss/allArticle.xml",
    "M094": "https://www.foodnews.news/data/rss/news.xml",
    "M099": "https://foodbeverageasia.com/feed/",
    "M110": "https://nielseniq.com/global/en/insights/feed/",
    "M111": "https://www.mintel.com/insights/food-and-drink/feed/",
    "M105": "https://www.minimeinsights.com/feed/",
    "M115": "https://tastewise.io/blog/feed",
}
RETIRED_PENDING_IDS = {
    "M005", "M009", "M011", "M020", "M021", "M022", "M024",
    "M026", "M028", "M032", "M033", "M034", "M036", "M039",
    "M040", "M042", "M044", "M050", "M055", "M056", "M058",
    "M060", "M061", "M063", "M064", "M065", "M112", "M113",
}
VERIFIED_JAPAN_HTML_SOURCES = {
    "M079": (
        "https://www.foodchemicalnews.co.jp/article/"
        "fcnhjnewspaper/foodchemicalnewspaper"
    ),
    "M085": "https://www.kenko-sokuho.co.jp/",
    "M087": "https://www.him-news.com/kiji.html",
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


def test_retired_sources_are_absent_from_generated_manifests(
    tmp_path,
):
    build_packs(SOURCE, tmp_path)

    found = {
        source.id
        for pack_id in PRIMARY_PACKS
        for source in _load(
            tmp_path / f"{pack_id}.json"
        ).sources
    }

    assert not ({"M006"} | RETIRED_PENDING_IDS) & found


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

    assert all(
        source.adapter in {"html_list", "rss"} for source in sources
    )
    assert all(source.enabled for source in sources)
    assert all(
        source.evidence_tier == EvidenceTier.INDUSTRY
        for source in sources
    )
    assert all(
        source.collection_tier == CollectionTier.EXTENDED
        for source in sources
    )
    assert all(
        source.options.get("item_selector")
        for source in sources
        if source.adapter == "html_list"
    )
    rss_urls = [
        urlsplit(source.url)
        for source in sources
        if source.adapter == "rss"
    ]
    assert all(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.path not in {"", "/"}
        for parsed in rss_urls
    )
    assert all(source.categories for source in sources)
    assert "reddit" not in json.dumps(
        [source.model_dump(mode="json") for source in sources]
    ).lower()


def test_verified_official_feeds_are_generated_as_rss_sources():
    sources = {
        source.id: source
        for pack_id in PRIMARY_PACKS
        for source in _load(PACK_DIR / f"{pack_id}.json").sources
    }

    actual = {
        source_id: (sources[source_id].adapter, sources[source_id].url)
        for source_id in VERIFIED_OFFICIAL_FEEDS
    }

    assert actual == {
        source_id: ("rss", url)
        for source_id, url in VERIFIED_OFFICIAL_FEEDS.items()
    }


def test_verified_japan_pages_use_current_html_contracts():
    sources = {
        source.id: source
        for pack_id in PRIMARY_PACKS
        for source in _load(PACK_DIR / f"{pack_id}.json").sources
    }

    for source_id, url in VERIFIED_JAPAN_HTML_SOURCES.items():
        source = sources[source_id]
        assert source.adapter == "html_list"
        assert str(source.url) == url
        assert source.options["require_content"] is True
        assert source.options["url_include_pattern"]


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
