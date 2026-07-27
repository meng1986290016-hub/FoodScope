"""Tests for China-hosted OpenAI-compatible AI providers."""

from __future__ import annotations

import pytest

from src.ai.client import OpenAIClient, create_ai_client
from src.models import AIConfig, AIProvider, AI_PROVIDER_DEFAULTS


PROVIDERS = [
    (
        AIProvider.ZHIPU,
        "glm-5.2",
        "ZHIPU_API_KEY",
        "https://open.bigmodel.cn/api/paas/v4",
    ),
    (
        AIProvider.QIANFAN,
        "ernie-4.5-turbo-20260402",
        "QIANFAN_API_KEY",
        "https://qianfan.baidubce.com/v2",
    ),
    (
        AIProvider.HUNYUAN,
        "hunyuan-turbos-latest",
        "HUNYUAN_API_KEY",
        "https://api.hunyuan.cloud.tencent.com/v1",
    ),
    (
        AIProvider.SILICONFLOW,
        "Pro/zai-org/GLM-4.7",
        "SILICONFLOW_API_KEY",
        "https://api.siliconflow.cn/v1",
    ),
]


@pytest.mark.parametrize("provider,model,key_env,base_url", PROVIDERS)
def test_provider_defaults(provider, model, key_env, base_url):
    defaults = AI_PROVIDER_DEFAULTS[provider]
    assert defaults["model"] == model
    assert defaults["api_key_env"] == key_env
    assert defaults["base_url"] == base_url


@pytest.mark.parametrize("provider,model,key_env,base_url", PROVIDERS)
def test_provider_creates_openai_compatible_client(
    monkeypatch, provider, model, key_env, base_url
):
    monkeypatch.setenv(key_env, "test-key")
    config = AIConfig(
        provider=provider,
        model=model,
        api_key_env=key_env,
    )

    client = create_ai_client(config)

    assert isinstance(client, OpenAIClient)
    assert client.provider == provider.value
    assert str(client.client.base_url).rstrip("/") == base_url


@pytest.mark.parametrize("provider,model,key_env,_base_url", PROVIDERS)
def test_provider_missing_key_message_uses_expected_variable(
    monkeypatch, provider, model, key_env, _base_url
):
    monkeypatch.delenv(key_env, raising=False)
    config = AIConfig(
        provider=provider,
        model=model,
        api_key_env=key_env,
    )

    with pytest.raises(ValueError, match=key_env):
        create_ai_client(config)
