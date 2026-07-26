import json
from pathlib import Path

from src.foodscope.briefing import BriefFacts
from src.foodscope.rendering import FoodBriefRenderer


FIXTURE = Path(
    "tests/fixtures/foodscope/selected_brief_facts.json"
)


def load_facts() -> BriefFacts:
    return BriefFacts.model_validate(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


def factual_facts() -> BriefFacts:
    facts = load_facts()
    alert = facts.risk_alerts[0].model_copy(deep=True)
    launch = facts.must_read[0].model_copy(deep=True)
    news = facts.must_read[1].model_copy(deep=True)
    alert.metadata["foodscope_base_score"] = 9.0
    alert.metadata["foodscope_final_score"] = 9.0
    alert.metadata["source_name"] = "FDA"
    launch.metadata["foodscope_base_score"] = 7.8
    launch.metadata["foodscope_final_score"] = 9.18
    launch.metadata["source_name"] = "FoodNavigator"
    assert launch.food is not None
    launch.food.key_facts_zh = [
        "产品规格为 350 毫升。",
        "首发渠道为日本零售市场。",
    ]
    news.metadata["foodscope_base_score"] = 5.99
    news.metadata["foodscope_final_score"] = 7.1
    news.metadata["discovered_source_name"] = "Retail News"
    assert news.food is not None
    news.food.key_facts_zh = ["报道覆盖英国和欧盟市场。"]
    return facts.model_copy(
        update={
            "risk_alerts": [],
            "must_read": [alert, launch],
            "news": [news],
            "sections": {},
        },
        deep=True,
    )


def test_fact_hash_is_stable_for_canonical_payload():
    first = load_facts()
    second = BriefFacts.model_validate_json(
        first.model_dump_json()
    )

    assert first.fact_hash() == second.fact_hash()
    assert len(first.fact_hash()) == 64


def test_markdown_and_html_share_one_fact_hash():
    facts = factual_facts()
    rendered = FoodBriefRenderer().render(facts)

    assert rendered.facts_sha256 == facts.fact_hash()
    assert rendered.facts_sha256 in rendered.markdown
    assert rendered.facts_sha256 in rendered.html
    assert "今日必读" in rendered.markdown
    assert "今日新闻" in rendered.markdown
    assert "仅供行业研究参考，不构成法律或合规意见" in (
        rendered.html
    )


def test_empty_profile_sections_are_not_rendered():
    rendered = FoodBriefRenderer().render(load_facts())

    assert "## 空栏目" not in rendered.markdown
    assert "<h2>空栏目</h2>" not in rendered.html


def test_item_details_are_factual_and_consistent_across_formats():
    rendered = FoodBriefRenderer().render(factual_facts())

    for expected in (
        "Example 在日本推出蛋白茶",
        "Example launches Protein Tea in Japan",
        "产品规格为 350 毫升。",
        "FoodNavigator",
        "2026-07-24 12:00（北京时间）",
    ):
        assert expected in rendered.markdown
        assert expected in rendered.html
    for forbidden in (
        "三句摘要",
        "对中国企业的意义",
        "研发意义",
        "机会信号",
        "风险信号",
        "建议动作",
        "证据：",
    ):
        assert forbidden not in rendered.markdown
        assert forbidden not in rendered.html


def test_items_are_not_repeated_across_score_sections():
    rendered = FoodBriefRenderer().render(factual_facts())
    title = "Example launches Protein Tea in Japan"

    assert rendered.markdown.count(title) == 1
    assert rendered.html.count(title) == 1


def test_legacy_category_only_items_remain_renderable():
    facts = load_facts()
    legacy_item = facts.must_read[1]
    legacy = facts.model_copy(
        update={
            "risk_alerts": [],
            "must_read": [],
            "news": [],
            "sections": {"consumer_trends": [legacy_item]},
        },
        deep=True,
    )

    rendered = FoodBriefRenderer().render(legacy)

    assert legacy_item.title in rendered.markdown
    assert legacy_item.title in rendered.html
