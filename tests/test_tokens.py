from src.ai.tokens import (
    get_usage_snapshot,
    record_usage,
    reset_usage,
)


def test_usage_snapshot_is_immutable_and_tracks_models():
    reset_usage()
    record_usage(
        "openai",
        input_tokens=10,
        output_tokens=5,
        model="gpt-test",
    )
    first = get_usage_snapshot()

    record_usage(
        "openai",
        input_tokens=3,
        output_tokens=2,
        model="gpt-test",
    )
    second = get_usage_snapshot()

    assert first.total_tokens == 15
    assert first.per_provider["openai"].total == 15
    assert first.per_model["openai/gpt-test"].total == 15
    assert second.total_tokens == 20
    assert second.per_model["openai/gpt-test"].total == 20
    reset_usage()
