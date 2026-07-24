from src.foodscope.models import (
    CollectionTier,
    EvidenceTier,
    FoodCategory,
    FoodIntelligence,
    ProductLaunchDetails,
    RiskLevel,
)


def test_product_launch_analysis_is_structured():
    food = FoodIntelligence(
        category=FoodCategory.PRODUCT_INNOVATION,
        markets=["JP"],
        importance_score=8.0,
        profile_relevance_score=9.0,
        opportunity_score=7.5,
        evidence_quality_score=8.5,
        risk_level=RiskLevel.LOW,
        evidence_tier=EvidenceTier.INDUSTRY,
        collection_tier=CollectionTier.CORE,
        product_launch=ProductLaunchDetails(
            brand="Example",
            product_name="Protein Tea",
            launch_markets=["JP"],
            launch_type="new_product",
        ),
    )

    assert food.category == FoodCategory.PRODUCT_INNOVATION
    assert food.product_launch is not None
    assert food.product_launch.product_name == "Protein Tea"
