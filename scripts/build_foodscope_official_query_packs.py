#!/usr/bin/env python3
"""Build official-evidence and discovery-query source manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


EXPECTED_OFFICIAL = {
    "global_codex_news",
    "global_wto_sps",
    "us_fda_food_recalls",
    "us_fda_outbreaks",
    "us_openfda_enforcement",
    "us_fda_food_guidance",
    "us_fsis_recalls",
    "eu_ec_food_safety_news",
    "eu_rasff",
    "eu_efsa_news",
    "eu_eurlex_food_law",
    "uk_fsa_food_alerts",
    "jp_caa_food_labeling",
    "jp_caa_food_recalls",
    "jp_caa_food_standards",
    "kr_mfds_press",
    "kr_mfds_standards",
    "sg_sfa_food_alerts",
    "sg_sfa_newsroom",
    "vn_vfa_news",
}

EXPECTED_QUERIES = {
    "en_product_launch",
    "en_ingredient_innovation",
    "en_fermentation",
    "en_alternative_protein",
    "en_functional_food",
    "en_reformulation",
    "en_food_packaging",
    "en_processing_technology",
    "en_consumer_trends",
    "en_retail_foodservice",
    "en_brand_strategy",
    "en_investment_ma",
    "en_capacity_expansion",
    "ja_product_launch",
    "ja_ingredient_technology",
    "ja_market_retail",
    "ko_product_launch",
    "ko_ingredient_technology",
    "ko_market_retail",
    "en_southeast_asia",
}

_OFFICIAL_ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*"
    r"([^|]+?)\s*\|\s*\[([^\]]+)\]\((https?://[^)]+)\)"
    r"\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*"
    r"([^|]+?)\s*\|$"
)
_QUERY_ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*"
    r"([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|$"
)

_CATEGORY_LABELS = (
    ("产品创新", "product_innovation"),
    ("原料与技术", "ingredients_technology"),
    ("加工技术", "ingredients_technology"),
    ("食品科技", "ingredients_technology"),
    ("包装与标签", "packaging_labeling"),
    ("消费趋势", "consumer_trends"),
    ("市场趋势", "consumer_trends"),
    ("法规与标准", "regulations_standards"),
    ("食品安全与召回", "food_safety_recalls"),
    ("食品安全", "food_safety_recalls"),
    ("零售餐饮", "retail_foodservice"),
    ("餐饮经营", "retail_foodservice"),
    ("企业动态", "company_updates"),
    ("品牌策略", "company_updates"),
    ("投融资", "company_updates"),
)

_JSON_OPTIONS = {
    "us_openfda_enforcement": {
        "items_path": "results",
        "title_field": "reason_for_recall",
        "url_field": "_foodscope_url",
        "date_field": "report_date",
        "content_field": "product_description",
        "id_field": "event_id",
    },
    "us_fsis_recalls": {
        "items_path": "",
        "title_field": "RecallTitle",
        "url_field": "RecallURL",
        "date_field": "RecallDate",
        "content_field": "Summary",
        "id_field": "RecallID",
    },
    "uk_fsa_food_alerts": {
        "items_path": "items",
        "title_field": "title",
        "url_field": "@id",
        "date_field": "created",
        "content_field": "description",
        "id_field": "@id",
    },
}


def _categories(value: str) -> list[str]:
    categories = [
        category
        for label, category in _CATEGORY_LABELS
        if label in value
    ]
    return list(dict.fromkeys(categories)) or ["company_updates"]


def _languages(value: str) -> list[str]:
    if "日语" in value:
        return ["ja"]
    if "韩语" in value:
        return ["ko"]
    if "越南语" in value:
        return ["vi"]
    return ["en"]


def _markets(value: str, source_id: str | None = None) -> list[str]:
    if source_id:
        prefix_map = {
            "global_": "GLOBAL",
            "us_": "US",
            "eu_": "EU",
            "uk_": "GB",
            "jp_": "JP",
            "kr_": "KR",
            "sg_": "SG",
            "vn_": "VN",
        }
        for prefix, market in prefix_map.items():
            if source_id.startswith(prefix):
                return [market]
    for marker, market in (
        ("日本", "JP"),
        ("韩国", "KR"),
        ("东南亚", "SEA"),
        ("全球", "GLOBAL"),
    ):
        if marker in value:
            return [market]
    return ["GLOBAL"]


def _adapter(method: str) -> str:
    if "RSS" in method:
        return "rss"
    if "JSON API" in method:
        return "json_api"
    if "PDF" in method or "HWPX" in method:
        return "document_index"
    return "html_list"


def _selector_options(method: str) -> dict[str, Any]:
    return {
        "date_selector": "time",
        "item_selector": "article, li",
        "link_selector": "a[href]",
        "max_content_chars": 1200,
        "source_collection_method": method,
        "title_selector": "h1, h2, h3, a[href]",
    }


def _parse_catalog(path: Path) -> tuple[list[dict], list[dict]]:
    official: list[dict] = []
    queries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _OFFICIAL_ROW.match(line)
        if match and match.group(1) in EXPECTED_OFFICIAL:
            (
                source_id,
                priority,
                name,
                url,
                method,
                language,
                categories,
            ) = match.groups()
            official.append(
                {
                    "id": source_id,
                    "priority": priority.strip(),
                    "name": name.strip(),
                    "url": url.strip(),
                    "method": method.strip(),
                    "language": language.strip(),
                    "category_text": categories.strip(),
                }
            )
            continue
        match = _QUERY_ROW.match(line)
        if match and match.group(1) in EXPECTED_QUERIES:
            query_id, market_language, query, category_text = (
                match.groups()
            )
            queries.append(
                {
                    "id": query_id,
                    "market_language": market_language.strip(),
                    "query": query,
                    "category_text": category_text.strip(),
                }
            )

    if {row["id"] for row in official} != EXPECTED_OFFICIAL:
        raise ValueError("official source IDs differ from expected set")
    if {row["id"] for row in queries} != EXPECTED_QUERIES:
        raise ValueError("query IDs differ from expected set")
    return official, queries


def _official_source(row: dict[str, str]) -> dict[str, Any]:
    adapter = _adapter(row["method"])
    options: dict[str, Any] = {
        "source_collection_method": row["method"],
        "source_priority": row["priority"],
    }
    if adapter == "json_api":
        options.update(_JSON_OPTIONS[row["id"]])
    elif adapter in {"html_list", "document_index"}:
        options.update(_selector_options(row["method"]))
    collection_tier = (
        "core"
        if any(
            marker in row["id"]
            for marker in (
                "recall",
                "outbreak",
                "enforcement",
                "rasff",
                "alert",
            )
        )
        else "extended"
    )
    return {
        "adapter": adapter,
        "categories": _categories(row["category_text"]),
        "collection_tier": collection_tier,
        "enabled": True,
        "evidence_tier": 1,
        "id": row["id"],
        "languages": _languages(row["language"]),
        "markets": _markets(row["language"], row["id"]),
        "name": row["name"],
        "options": options,
        "packs": ["official_evidence"],
        "url": row["url"],
    }


def _query_source(row: dict[str, str]) -> dict[str, Any]:
    languages = _languages(row["market_language"])
    categories = _categories(row["category_text"])
    providers = (
        ["google_news"]
        if languages[0] in {"ja", "ko"}
        else ["google_news", "gdelt"]
    )
    return {
        "adapter": "discovery_query",
        "categories": categories,
        "collection_tier": "discovery",
        "enabled": True,
        "evidence_tier": 3,
        "id": row["id"],
        "languages": languages,
        "markets": _markets(row["market_language"]),
        "name": row["id"],
        "options": {
            "category_hint": categories,
            "max_candidates_after_dedup": 12,
            "max_candidates_per_provider": 20,
            "providers": providers,
            "query": row["query"],
        },
        "packs": ["discovery_queries"],
        "url": "https://news.google.com/rss/search",
    }


def _write(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def build_packs(catalog: Path, output_dir: Path) -> None:
    official_rows, query_rows = _parse_catalog(catalog)
    _write(
        output_dir / "official_evidence.json",
        {
            "id": "official_evidence",
            "name": "全球食品法规、安全与召回官方证据",
            "sources": sorted(
                (_official_source(row) for row in official_rows),
                key=lambda source: source["id"],
            ),
        },
    )
    _write(
        output_dir / "discovery_queries.json",
        {
            "id": "discovery_queries",
            "name": "多语言食品产业发现查询",
            "sources": sorted(
                (_query_source(row) for row in query_rows),
                key=lambda source: source["id"],
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(
            "docs/superpowers/specs/"
            "2026-07-23-foodscope-source-catalog.md"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/foodscope/source_packs"),
    )
    args = parser.parse_args()
    build_packs(args.catalog, args.output)


if __name__ == "__main__":
    main()
