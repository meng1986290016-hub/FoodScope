#!/usr/bin/env python3
"""Build deterministic media source packs from the audited Markdown."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


EXPECTED_KEEP = {
    "M001", "M002", "M003", "M004", "M005", "M006", "M007",
    "M009", "M011", "M012", "M017", "M019", "M020", "M021",
    "M022", "M024", "M026", "M028", "M030", "M032", "M033",
    "M034", "M035", "M036", "M039", "M040", "M042", "M044",
    "M050", "M055", "M056", "M058", "M060", "M061", "M063",
    "M064", "M065", "M075", "M076", "M079", "M080", "M084",
    "M085", "M086", "M087", "M089", "M090", "M091", "M092",
    "M093", "M094", "M098", "M099", "M105", "M110", "M111",
    "M112", "M113", "M115",
}

PRIMARY_PACK_RANGES = (
    (1, 18, "global_industry"),
    (19, 36, "ingredients_rd"),
    (37, 54, "packaging_processing"),
    (55, 74, "retail_foodservice"),
    (75, 88, "japan"),
    (89, 97, "korea"),
    (98, 109, "southeast_asia"),
    (110, 120, "research_data"),
)

PRODUCT_LAUNCH_IDS = {
    "M001", "M002", "M003", "M004", "M019", "M021", "M030",
    "M035", "M055", "M075", "M076", "M089", "M090", "M091",
    "M092", "M098", "M105",
}

PACK_NAMES = {
    "global_industry": "全球食品工业媒体",
    "ingredients_rd": "配料、营养与研发",
    "packaging_processing": "包装、加工与供应链",
    "retail_foodservice": "零售、便利店与餐饮",
    "japan": "日本食品产业",
    "korea": "韩国食品产业",
    "southeast_asia": "东南亚与亚太食品产业",
    "research_data": "数据、研究与商业信号",
    "product_launches": "全球食品新品雷达",
}

_WILLIAM_REED_OPTIONS = {
    "detail_content_selector": ".b-article-body",
    "date_selector": "time",
    "exclude_text_pattern": "(?i)Paid for by",
    "item_selector": "article.card",
    "link_selector": ".card-text-headline a",
    "max_detail_content_fetches": 20,
    "require_content": True,
    "title_selector": ".card-text-headline a",
    "url_include_pattern": "/Article/",
}

_DIRECT_SOURCE_OVERRIDES: dict[str, dict[str, Any]] = {
    "M001": {"options": _WILLIAM_REED_OPTIONS},
    "M002": {
        "adapter": "rss",
        "options": {},
        "url": "https://www.foodbusinessnews.net/rss/2",
    },
    "M017": {
        "options": {
            "date_selector": ".meta",
            "date_text_pattern": r"posted\s+(.+)",
            "detail_content_selector": ".articleContent",
            "detail_date_jsonld_field": "datePublished",
            "item_selector": "article",
            "link_selector": (
                ".articleExcerpt h2 a, .articleExcerpt h3 a"
            ),
            "max_detail_content_fetches": 20,
            "max_detail_date_fetches": 20,
            "prefer_detail_date": True,
            "require_content": True,
            "title_selector": (
                ".articleExcerpt h2 a, .articleExcerpt h3 a"
            ),
            "url_include_pattern": "/news/",
        }
    },
    "M019": {"options": _WILLIAM_REED_OPTIONS},
    "M030": {
        "adapter": "rss",
        "options": {},
        "url": (
            "https://www.bakingbusiness.com/rss/topic/1227-news"
        ),
    },
    "M035": {
        "options": _WILLIAM_REED_OPTIONS,
        "url": "https://www.confectionerynews.com/News/",
    },
}

_CANDIDATE_ROW = re.compile(
    r"^\|\s*(M\d{3})\s*\|\s*"
    r"\[([^\]]+)\]\((https?://[^)]+)\)\s*\|\s*"
    r"([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*"
    r"([ABC])\s*\|\s*([^|]+?)\s*\|$"
)
_DECISION_ROW = re.compile(
    r"^\|\s*(M\d{3})\s*\|\s*`([^`]+)`\s*\|"
)

_CATEGORY_KEYWORDS = (
    (
        "product_innovation",
        ("新品", "菜单", "风味", "配方"),
    ),
    (
        "ingredients_technology",
        (
            "配料", "原料", "研发", "技术", "科学", "添加剂",
            "营养", "发酵", "蛋白",
        ),
    ),
    (
        "packaging_labeling",
        (
            "包装", "设备", "加工", "工厂", "自动化", "制造",
            "工程", "材料",
        ),
    ),
    (
        "consumer_trends",
        ("消费", "趋势", "价格", "销售", "市场", "品类"),
    ),
    (
        "regulations_standards",
        ("法规", "政策", "标准", "合规"),
    ),
    (
        "food_safety_recalls",
        ("安全", "召回", "质量", "检测"),
    ),
    (
        "retail_foodservice",
        (
            "零售", "餐饮", "门店", "商超", "便利店", "渠道",
            "流通", "外食", "菜单",
        ),
    ),
    (
        "company_updates",
        (
            "企业", "并购", "融资", "投资", "交易", "品牌",
            "供应链", "创业", "项目",
        ),
    ),
)


def _parse_markdown(path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    candidates: dict[str, dict] = {}
    decisions: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = _CANDIDATE_ROW.match(line)
        if candidate:
            (
                candidate_id,
                name,
                url,
                market_language,
                signals,
                grade,
                note,
            ) = candidate.groups()
            if candidate_id in candidates:
                raise ValueError(
                    f"duplicate candidate row: {candidate_id}"
                )
            candidates[candidate_id] = {
                "id": candidate_id,
                "name": name.strip(),
                "url": url.strip(),
                "market_language": market_language.strip(),
                "signals": signals.strip(),
                "initial_grade": grade,
                "note": note.strip(),
            }
            continue
        decision = _DECISION_ROW.match(line)
        if decision:
            candidate_id, value = decision.groups()
            if candidate_id in decisions:
                raise ValueError(
                    f"duplicate decision row: {candidate_id}"
                )
            decisions[candidate_id] = value

    expected_candidates = {
        f"M{number:03d}" for number in range(1, 121)
    }
    if set(candidates) != expected_candidates:
        raise ValueError(
            "candidate table IDs differ from M001-M120"
        )
    return candidates, decisions


def _primary_pack(candidate_id: str) -> str:
    number = int(candidate_id[1:])
    for start, end, pack_id in PRIMARY_PACK_RANGES:
        if start <= number <= end:
            return pack_id
    raise ValueError(f"no primary pack for {candidate_id}")


def _languages(value: str) -> list[str]:
    mapped = [
        code
        for marker, code in (
            ("日语", "ja"),
            ("韩语", "ko"),
            ("泰语", "th"),
            ("越南语", "vi"),
            ("英语", "en"),
        )
        if marker in value
    ]
    return mapped or ["en"]


def _markets(value: str) -> list[str]:
    mapped = [
        code
        for marker, code in (
            ("日本", "JP"),
            ("韩国", "KR"),
            ("越南", "VN"),
            ("泰国", "TH"),
            ("美国", "US"),
            ("英国", "GB"),
            ("欧洲", "EU"),
            ("东南亚", "SEA"),
            ("亚太", "APAC"),
            ("亚洲", "APAC"),
            ("全球", "GLOBAL"),
        )
        if marker in value
    ]
    return list(dict.fromkeys(mapped)) or ["GLOBAL"]


def _categories(signals: str) -> list[str]:
    categories = [
        category
        for category, keywords in _CATEGORY_KEYWORDS
        if any(keyword in signals for keyword in keywords)
    ]
    return categories or ["company_updates"]


def _source_record(
    candidate: dict[str, str], pack_id: str
) -> dict[str, Any]:
    categories = _categories(candidate["signals"])
    if candidate["id"] in PRODUCT_LAUNCH_IDS:
        categories = list(
            dict.fromkeys(["product_innovation"] + categories)
        )
    trial_options = {
        "max_content_chars": 1200,
        "trial_initial_grade": candidate["initial_grade"],
        "trial_note": candidate["note"],
        "trial_signals": candidate["signals"],
    }
    record = {
        "adapter": "html_list",
        "categories": categories,
        "collection_tier": "extended",
        "enabled": True,
        "evidence_tier": 2,
        "id": candidate["id"],
        "languages": _languages(candidate["market_language"]),
        "markets": _markets(candidate["market_language"]),
        "name": candidate["name"],
        "options": {
            "content_selector": "p",
            "date_selector": "time",
            "item_selector": "article",
            "link_selector": "a[href]",
            "title_selector": "h1, h2, h3",
            **trial_options,
        },
        "packs": [pack_id],
        "url": candidate["url"],
    }
    override = _DIRECT_SOURCE_OVERRIDES.get(candidate["id"])
    if override is None:
        return record
    record.update(
        {
            key: value
            for key, value in override.items()
            if key != "options"
        }
    )
    record["options"] = {
        **trial_options,
        **override.get("options", {}),
    }
    return record


def _write_manifest(
    output_dir: Path, pack_id: str, sources: list[dict]
) -> None:
    manifest = {
        "id": pack_id,
        "name": PACK_NAMES[pack_id],
        "sources": sorted(sources, key=lambda source: source["id"]),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{pack_id}.json").write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def build_packs(source_path: Path, output_dir: Path) -> None:
    candidates, decisions = _parse_markdown(source_path)
    retained = {
        candidate_id
        for candidate_id, decision in decisions.items()
        if decision == "keep"
    }
    if retained != EXPECTED_KEEP:
        raise ValueError(
            "Markdown keep decisions differ from EXPECTED_KEEP: "
            f"missing={sorted(EXPECTED_KEEP - retained)}, "
            f"unexpected={sorted(retained - EXPECTED_KEEP)}"
        )

    packs: dict[str, list[dict]] = {
        pack_id: []
        for _, _, pack_id in PRIMARY_PACK_RANGES
    }
    product_sources: list[dict] = []
    for candidate_id in sorted(retained):
        pack_id = _primary_pack(candidate_id)
        primary = _source_record(
            candidates[candidate_id], pack_id
        )
        packs[pack_id].append(primary)
        if candidate_id in PRODUCT_LAUNCH_IDS:
            product = dict(primary)
            product["options"] = dict(primary["options"])
            product["packs"] = [
                pack_id,
                "product_launches",
            ]
            product_sources.append(product)

    for pack_id, sources in packs.items():
        _write_manifest(output_dir, pack_id, sources)
    _write_manifest(
        output_dir, "product_launches", product_sources
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            "docs/superpowers/specs/"
            "2026-07-23-foodscope-industry-media-longlist.md"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/foodscope/source_packs"),
    )
    args = parser.parse_args()
    build_packs(args.source, args.output)


if __name__ == "__main__":
    main()
