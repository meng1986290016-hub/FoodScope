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


def test_fact_hash_is_stable_for_canonical_payload():
    first = load_facts()
    second = BriefFacts.model_validate_json(
        first.model_dump_json()
    )

    assert first.fact_hash() == second.fact_hash()
    assert len(first.fact_hash()) == 64


def test_markdown_and_html_share_one_fact_hash():
    facts = load_facts()
    rendered = FoodBriefRenderer().render(facts)

    assert rendered.facts_sha256 == facts.fact_hash()
    assert rendered.facts_sha256 in rendered.markdown
    assert rendered.facts_sha256 in rendered.html
    assert "重大风险提醒" in rendered.markdown
    assert "今日必读" in rendered.markdown
    assert "仅供行业研究参考，不构成法律或合规意见" in (
        rendered.html
    )


def test_empty_profile_sections_are_not_rendered():
    rendered = FoodBriefRenderer().render(load_facts())

    assert "## 空栏目" not in rendered.markdown
    assert "<h2>空栏目</h2>" not in rendered.html


def test_item_details_and_evidence_are_consistent_across_formats():
    rendered = FoodBriefRenderer().render(load_facts())

    for expected in (
        "Example 在日本推出蛋白茶",
        "Example launches Protein Tea in Japan",
        "需要关注蛋白体系在茶基底中的稳定性与口感",
        "https://company.example/protein-tea",
        "evidence tier 2",
    ):
        assert expected in rendered.markdown
        assert expected in rendered.html
