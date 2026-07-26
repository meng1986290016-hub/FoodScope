"""Food-industry domain models."""

from enum import IntEnum, StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class FoodCategory(StrEnum):
    """The single primary category assigned to a food-industry event."""

    PRODUCT_INNOVATION = "product_innovation"
    INGREDIENTS_TECHNOLOGY = "ingredients_technology"
    PACKAGING_LABELING = "packaging_labeling"
    CONSUMER_TRENDS = "consumer_trends"
    REGULATIONS_STANDARDS = "regulations_standards"
    FOOD_SAFETY_RECALLS = "food_safety_recalls"
    RETAIL_FOODSERVICE = "retail_foodservice"
    COMPANY_UPDATES = "company_updates"


class EvidenceTier(IntEnum):
    """Evidence authority, where a lower number is stronger."""

    PRIMARY = 1
    INDUSTRY = 2
    DISCOVERY = 3
    WEAK_SIGNAL = 4


class CollectionTier(StrEnum):
    """Collection frequency and cost policy."""

    CORE = "core"
    EXTENDED = "extended"
    DISCOVERY = "discovery"


class RiskLevel(StrEnum):
    """Potential food-industry risk severity."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SEVERE = "severe"


class ProductLaunchDetails(BaseModel):
    """Structured fields extracted for a real product launch."""

    brand: Optional[str] = None
    company: Optional[str] = None
    product_name: str
    launch_markets: list[str] = Field(default_factory=list)
    launch_date: Optional[str] = None
    audience: list[str] = Field(default_factory=list)
    ingredients: list[str] = Field(default_factory=list)
    flavors: list[str] = Field(default_factory=list)
    format: Optional[str] = None
    claims: list[str] = Field(default_factory=list)
    package_size: Optional[str] = None
    price: Optional[str] = None
    channels: list[str] = Field(default_factory=list)
    launch_type: str


class FoodIntelligence(BaseModel):
    """FoodScope analysis attached to a Horizon content item."""

    category: FoodCategory
    markets: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    ingredient_tags: list[str] = Field(default_factory=list)
    technology_tags: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    importance_score: float = Field(ge=0, le=10)
    profile_relevance_score: float = Field(ge=0, le=10)
    opportunity_score: float = Field(ge=0, le=10)
    evidence_quality_score: float = Field(ge=0, le=10)
    risk_level: RiskLevel
    risk_reason: str = ""
    what_happened_zh: str = ""
    key_facts_zh: list[str] = Field(default_factory=list)
    why_it_matters_zh: str = ""
    rd_significance_zh: str = ""
    opportunity_signal_zh: str = ""
    risk_signal_zh: str = ""
    recommended_action_zh: str = ""
    evidence_tier: EvidenceTier
    collection_tier: CollectionTier
    source_id: str = ""
    source_pack_ids: list[str] = Field(default_factory=list)
    event_key: Optional[str] = None
    original_source_url: Optional[str] = None
    evidence_urls: list[str] = Field(default_factory=list)
    official_evidence_urls: list[str] = Field(default_factory=list)
    sponsored: bool = False
    press_release: bool = False
    selection_reason: str = ""
    product_launch: Optional[ProductLaunchDetails] = None
