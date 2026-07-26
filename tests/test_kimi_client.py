"""Tests for Kimi (Moonshot) AI client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.client import OpenAIClient, create_ai_client
from src.models import AIConfig, AIProvider, AI_PROVIDER_DEFAULTS


def _make_config(**overrides) -> AIConfig:
    defaults = {
        "provider": AIProvider.KIMI,
        "model": "kimi-k2.6",
        "api_key_env": "KIMI_API_KEY",
        "temperature": 0.6,
        "max_tokens": 4096,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    defaults.update(overrides)
    return AIConfig(**defaults)


class TestKimiClientInit:
    def test_creates_instance_with_valid_config(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        client = OpenAIClient(_make_config())
        assert client.model == "kimi-k2.6"
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


class TestKimiCompletion:
    def test_forwards_disabled_thinking_extra_body(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        client = OpenAIClient(_make_config())

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok":true}'
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch.object(
            client.client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            result = asyncio.run(client.complete(system="Return JSON.", user="Ping"))

        assert result == '{"ok":true}'
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == "kimi-k2.6"
        assert call_kwargs["temperature"] == 0.6
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert call_kwargs["response_format"] == {"type": "json_object"}


class TestKimiFactoryFunction:
    def test_kimi_provider_defaults(self):
        defaults = AI_PROVIDER_DEFAULTS[AIProvider.KIMI]
        assert defaults["model"] == "kimi-k2.6"
        assert defaults["base_url"] == "https://api.moonshot.cn/v1"
        assert defaults["api_key_env"] == "KIMI_API_KEY"
        assert defaults["temperature"] == 0.6
        assert defaults["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_creates_openai_client_for_kimi(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "test-key")
        config = _make_config()
        client = create_ai_client(config)
        assert isinstance(client, OpenAIClient)
        assert client.provider == "kimi"

    def test_kimi_provider_enum(self):
        assert AIProvider.KIMI.value == "kimi"
