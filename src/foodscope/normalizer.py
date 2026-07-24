"""Normalize FoodScope items before AI analysis."""

import re

from src.models import ContentItem

from .config import FoodSourceSpec
from .models import EvidenceTier, FoodCategory, FoodIntelligence, RiskLevel


def normalize_item(
    item: ContentItem, source: FoodSourceSpec
) -> ContentItem:
    """Attach the source contract and normalize basic item metadata."""

    item.title = re.sub(r"\s+", " ", item.title).strip()
    item.metadata.update(
        {
            "food_source_id": source.id,
            "source_name": source.name,
            "source_pack_ids": source.packs,
            "markets": source.markets,
            "languages": source.languages,
        }
    )
    if item.food is None:
        category = (
            source.categories[0]
            if source.categories
            else FoodCategory.COMPANY_UPDATES
        )
        item_url = str(item.url)
        original_source_url = (
            item.metadata.get("resolved_original_url")
            if source.evidence_tier >= EvidenceTier.DISCOVERY
            else item_url
        )
        item.food = FoodIntelligence(
            category=category,
            markets=source.markets,
            importance_score=0,
            profile_relevance_score=0,
            opportunity_score=0,
            evidence_quality_score=0,
            risk_level=RiskLevel.NONE,
            evidence_tier=source.evidence_tier,
            collection_tier=source.collection_tier,
            source_id=source.id,
            source_pack_ids=source.packs,
            original_source_url=original_source_url,
            evidence_urls=[item_url],
            official_evidence_urls=(
                [item_url]
                if source.evidence_tier == EvidenceTier.PRIMARY
                else []
            ),
        )
    return item
