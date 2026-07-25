"""Tests for Kimi (Moonshot) AI client."""

from __future__ import annotations

import pytest

from src.ai.client import OpenAIClient, create_ai_client
from src.models import AIConfig, AIProvider, AI_PROVIDER_DEFAULTS


def _make_config(**overrides) -> AIConfig:
    defaults = {
        "provider": AIProvider.KIMI,
        "model": "moonshot-v1-8k",
        "api_key_env": "KIMI_API_KEY",
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    defaults.update(overrides)
    return AIConfig(**defaults)


class TestKimiClientInit:
    def test_creates_instance_with_valid_config(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        client = OpenAIClient(_make_config())
        assert client.model == "moonshot-v1-8k"
        assert client.provider == "kimi"

    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="Missing API key"):
            OpenAIClient(_make_config())

    def test_uses_provider_default_base_url(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        client = OpenAIClient(_make_config())
        assert str(client.client.base_url).rstrip("/") == "https://api.moonshot.cn/v1"

    def test_uses_custom_base_url(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        client = OpenAIClient(_make_config(base_url="https://api.moonshot.cn/custom/v1"))
        assert str(client.client.base_url).rstrip("/") == "https://api.moonshot.cn/custom/v1"


class TestKimiFactoryFunction:
    def test_kimi_provider_defaults(self):
        defaults = AI_PROVIDER_DEFAULTS[AIProvider.KIMI]
        assert defaults["model"] == "moonshot-v1-8k"
        assert defaults["base_url"] == "https://api.moonshot.cn/v1"
        assert defaults["api_key_env"] == "KIMI_API_KEY"

    def test_creates_openai_client_for_kimi(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        config = _make_config()
        client = create_ai_client(config)
        assert isinstance(client, OpenAIClient)
        assert client.provider == "kimi"

    def test_kimi_provider_enum(self):
        assert AIProvider.KIMI.value == "kimi"
