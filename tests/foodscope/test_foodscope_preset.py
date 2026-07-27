from src.setup.presets import build_foodscope_preset


def test_foodscope_preset_uses_selected_ai_for_both_routes():
    selected_ai = {
        "provider": "openai",
        "model": "gpt-4",
        "api_key_env": "OPENAI_API_KEY",
    }

    preset = build_foodscope_preset(selected_ai)

    assert preset["ai_routes"]["fast"] == selected_ai
    assert preset["ai_routes"]["analysis"] == selected_ai
    assert preset["foodscope"]["profile"] == "balanced"
    assert preset["foodscope"]["source_packs"] == [
        "official_evidence",
        "global_industry",
        "ingredients_rd",
        "japan",
        "korea",
        "southeast_asia",
        "research_data",
        "product_launches",
        "discovery_queries",
        "x_watch",
    ]
    assert preset["schedule"]["cron"] == "30 6 * * *"
    assert preset["collection"]["lookback_hours"] == 30
