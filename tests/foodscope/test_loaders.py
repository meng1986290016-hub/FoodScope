from pathlib import Path

import pytest

from src.foodscope.config import FoodScopeConfig
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
    (tmp_path / "balanced.json").write_text(
        '{"id":"market","name":"Wrong","topic_weights":'
        '{"product_innovation":1.0}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        load_profile(
            FoodScopeConfig(profile="balanced", profile_dir=tmp_path)
        )
