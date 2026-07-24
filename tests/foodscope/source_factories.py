from src.foodscope.config import FoodSourceSpec
from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
)


def source(
    source_id: str,
    adapter: str,
    *,
    url: str | None = None,
    options: dict | None = None,
    enabled: bool = True,
) -> FoodSourceSpec:
    return FoodSourceSpec(
        id=source_id,
        name=f"Source {source_id}",
        url=url or f"https://93.184.216.34/{source_id}",
        adapter=adapter,
        enabled=enabled,
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.EXTENDED,
        packs=["global_industry"],
        markets=["US"],
        languages=["en"],
        categories=[FoodCategory.PRODUCT_INNOVATION],
        options=options or {},
    )


def rss_source(
    source_id: str,
    *,
    url: str | None = None,
    enabled: bool = True,
) -> FoodSourceSpec:
    return source(
        source_id,
        "rss",
        url=url or f"https://93.184.216.34/{source_id}.xml",
        enabled=enabled,
    )
