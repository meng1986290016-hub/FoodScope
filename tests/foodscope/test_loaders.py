import json
from pathlib import Path

import pytest

from src.foodscope.config import BriefProfile, FoodScopeConfig
from src.foodscope.loaders import load_profile, load_source_packs
from src.foodscope.models import FoodCategory


def test_all_builtin_profiles_validate():
    root = Path("data/foodscope/profiles")

    for profile_id in ("balanced", "market", "new_products", "rd", "compliance"):
        profile = load_profile(
            FoodScopeConfig(profile=profile_id, profile_dir=root)
        )
        assert profile.id == profile_id
        assert abs(sum(profile.topic_weights.values()) - 1.0) < 0.0001


def test_balanced_profile_preserves_commercial_target():
    profile = load_profile(FoodScopeConfig(profile="balanced"))

    assert profile.commercial_min_ratio == 0.70
    assert profile.topic_weights[FoodCategory.PRODUCT_INNOVATION] == 0.20


def test_profile_requires_all_categories_and_bounded_weights():
    payload = json.loads(
        Path("data/foodscope/profiles/balanced.json").read_text(
            encoding="utf-8"
        )
    )
    payload["topic_weights"].pop("company_updates")
    payload["topic_weights"]["product_innovation"] += 0.1

    with pytest.raises(ValueError, match="all FoodCategory"):
        BriefProfile.model_validate(payload)

    payload = json.loads(
        Path("data/foodscope/profiles/balanced.json").read_text(
            encoding="utf-8"
        )
    )
    payload["topic_weights"]["product_innovation"] = -0.1
    payload["topic_weights"]["company_updates"] += 0.3

    with pytest.raises(ValueError, match="between 0 and 1"):
        BriefProfile.model_validate(payload)


@pytest.mark.parametrize("weight", [-0.1, 1.01])
def test_profile_market_weights_must_be_bounded(weight):
    payload = json.loads(
        Path("data/foodscope/profiles/balanced.json").read_text(
            encoding="utf-8"
        )
    )
    payload["market_weights"] = {"US": weight}

    with pytest.raises(
        ValueError, match="market_weights"
    ):
        BriefProfile.model_validate(payload)


def test_duplicate_sources_from_multiple_packs_are_merged(tmp_path):
    pack = (
        '{"id":"one","name":"One","sources":[{"id":"M001",'
        '"name":"FoodNavigator","url":"https://example.com","adapter":"rss",'
        '"evidence_tier":2,"collection_tier":"core","packs":["one"],'
        '"categories":["product_innovation"]}]}'
    )
    (tmp_path / "one.json").write_text(pack, encoding="utf-8")
    (tmp_path / "two.json").write_text(
        pack.replace('"one"', '"two"'), encoding="utf-8"
    )
    config = FoodScopeConfig(
        source_packs=["one", "two"], source_pack_dir=tmp_path
    )

    sources = load_source_packs(config)

    assert [source.id for source in sources] == ["M001"]
    assert sources[0].packs == ["one", "two"]


def test_builtin_profile_id_must_match_file_name(tmp_path):
    payload = json.loads(
        Path("data/foodscope/profiles/balanced.json").read_text(
            encoding="utf-8"
        )
    )
    payload["id"] = "market"
    payload["name"] = "Wrong"
    (tmp_path / "balanced.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        load_profile(
            FoodScopeConfig(profile="balanced", profile_dir=tmp_path)
        )


def test_first_direct_source_batch_uses_verified_entries_and_selectors():
    sources = {
        source.id: source
        for source in load_source_packs(
            FoodScopeConfig(
                source_packs=[
                    "global_industry",
                    "ingredients_rd",
                    "product_launches",
                ]
            )
        )
    }

    assert sources["M002"].adapter == "rss"
    assert sources["M002"].url == (
        "https://www.foodbusinessnews.net/rss/2"
    )
    assert sources["M030"].adapter == "rss"
    assert sources["M030"].url == (
        "https://www.bakingbusiness.com/rss/topic/1227-news"
    )
    for source_id in ("M001", "M019", "M035"):
        assert sources[source_id].options["item_selector"] == (
            "article.card"
        )
        assert sources[source_id].options["detail_content_selector"] == (
            ".b-article-body"
        )
        assert sources[source_id].options["require_content"] is True
    assert sources["M017"].options["date_text_pattern"] == (
        r"posted\s+(.+)"
    )
    assert sources["M017"].options["url_include_pattern"] == (
        r"/news/"
    )
    assert sources["M017"].options["detail_content_selector"] == (
        ".articleContent"
    )
    assert sources["M017"].options["prefer_detail_date"] is True
    assert sources["M017"].options["detail_date_jsonld_field"] == (
        "datePublished"
    )
