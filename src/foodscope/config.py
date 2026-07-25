"""Configuration contracts for the FoodScope extension."""

import math
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .models import CollectionTier, EvidenceTier, FoodCategory, RiskLevel


class ScheduleConfig(BaseModel):
    timezone: str = "Asia/Shanghai"
    cron: str = "30 6 * * *"


class CollectionConfig(BaseModel):
    lookback_hours: int = Field(default=30, gt=0, le=720)
    minimum_sources_per_run: int = Field(
        default=20, ge=1, le=500
    )
    extended_rotation_days: int = Field(
        default=2, ge=1, le=30
    )
    discovery_rotation_days: int = Field(
        default=3, ge=1, le=30
    )
    fallback_sources_per_run: int = Field(
        default=5, ge=0, le=50
    )


class WeChatDraftConfig(BaseModel):
    enabled: bool = False
    app_id_env: str = "WECHAT_APP_ID"
    app_secret_env: str = "WECHAT_APP_SECRET"
    thumb_media_id: Optional[str] = None
    author: str = "FoodScope"


class DeliveryConfig(BaseModel):
    target_minutes: int = Field(default=60, gt=0)
    markdown_enabled: bool = True
    html_enabled: bool = True
    wechat: WeChatDraftConfig = Field(default_factory=WeChatDraftConfig)


class FoodSourceSpec(BaseModel):
    id: str
    name: str
    url: str
    adapter: str
    enabled: bool = True
    evidence_tier: EvidenceTier
    collection_tier: CollectionTier
    packs: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    categories: list[FoodCategory] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class SourcePackManifest(BaseModel):
    id: str
    name: str
    sources: list[FoodSourceSpec]


class BriefProfile(BaseModel):
    id: str
    name: str
    max_items: int = Field(default=20, ge=15, le=25)
    max_per_source: int = Field(default=3, gt=0)
    exploration_slots: int = Field(default=2, ge=0)
    commercial_min_ratio: float = Field(default=0.0, ge=0, le=1)
    minimum_score: float = Field(default=6.0, ge=0, le=10)
    risk_override_min: RiskLevel = RiskLevel.HIGH
    topic_weights: dict[FoodCategory, float]
    market_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("topic_weights")
    @classmethod
    def weights_sum_to_one(
        cls, value: dict[FoodCategory, float]
    ) -> dict[FoodCategory, float]:
        if set(value) != set(FoodCategory):
            raise ValueError(
                "topic_weights must contain all FoodCategory values"
            )
        if any(
            not math.isfinite(weight)
            or weight < 0
            or weight > 1
            for weight in value.values()
        ):
            raise ValueError(
                "topic_weights must be finite and between 0 and 1"
            )
        if abs(sum(value.values()) - 1.0) > 0.0001:
            raise ValueError("topic_weights must sum to 1.0")
        return value

    @field_validator("market_weights")
    @classmethod
    def market_weights_are_non_negative(
        cls, value: dict[str, float]
    ) -> dict[str, float]:
        if any(
            not math.isfinite(weight)
            or weight < 0
            or weight > 1
            for weight in value.values()
        ):
            raise ValueError(
                "market_weights must be finite and between 0 and 1"
            )
        return value


class FoodScopeConfig(BaseModel):
    enabled: bool = False
    profile: str = "balanced"
    profile_path: Optional[Path] = None
    source_packs: list[str] = Field(
        default_factory=lambda: [
            "official_evidence",
            "global_industry",
            "product_launches",
        ]
    )
    source_pack_dir: Path = Path("data/foodscope/source_packs")
    profile_dir: Path = Path("data/foodscope/profiles")
    source_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    x_access_mode: Optional[Literal["official_api"]] = None
    x_bearer_token_env: Optional[str] = None
