import pytest

from src.models import Config


def legacy_config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "provider": "openai",
            "model": "gpt-4",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {
            "hackernews": {"enabled": False},
            "reddit": {"enabled": False},
            "telegram": {"enabled": False},
        },
        "filtering": {"ai_score_threshold": 6.0},
    }


def test_legacy_horizon_config_remains_valid():
    config = Config.model_validate(legacy_config())

    assert config.foodscope is None


def test_foodscope_defaults_to_balanced_profile():
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True}
    raw["ai_routes"] = {"fast": raw["ai"], "analysis": raw["ai"]}

    config = Config.model_validate(raw)

    assert config.foodscope is not None
    assert config.foodscope.profile == "balanced"
    assert config.schedule.timezone == "Asia/Shanghai"
    assert config.collection.lookback_hours == 30
    assert config.delivery.target_minutes == 60


def test_foodscope_requires_fast_and_analysis_routes():
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True}

    with pytest.raises(ValueError, match="ai_routes"):
        Config.model_validate(raw)


def test_ai_pricing_requires_input_and_output_rates_together():
    raw = legacy_config()
    raw["ai"]["input_cost_per_million"] = 1.25

    with pytest.raises(
        ValueError, match="must be set together"
    ):
        Config.model_validate(raw)
