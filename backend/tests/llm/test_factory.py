"""Provider selection — architecture.md §11a: `LLM_PROVIDER` config alone
selects the adapter; never anything hardcoded, never Claude mandatory.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.llm.base import LLMConfigurationError
from app.llm.factory import get_llm_provider
from app.llm.fake import FakeLLMProvider


def test_empty_provider_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_provider(Settings(llm_provider=""))


def test_unsupported_provider_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_provider(Settings(llm_provider="not-a-real-provider"))


def test_fake_provider_selected_without_any_api_key() -> None:
    provider = get_llm_provider(Settings(llm_provider="fake"))
    assert isinstance(provider, FakeLLMProvider)


def test_claude_without_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_provider(Settings(llm_provider="claude", llm_api_key="", llm_model="claude-x"))


def test_gemini_without_model_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_provider(Settings(llm_provider="gemini", llm_api_key="k", llm_model=""))


def test_grok_with_valid_config_constructs_successfully() -> None:
    provider = get_llm_provider(Settings(llm_provider="grok", llm_api_key="k", llm_model="grok-x"))
    assert provider.provider_name == "grok"


def test_groq_with_valid_config_constructs_successfully() -> None:
    # "groq" (the inference platform) is deliberately distinct from "grok"
    # (xAI) above — both must resolve independently and correctly.
    provider = get_llm_provider(Settings(llm_provider="groq", llm_api_key="k", llm_model="openai/gpt-oss-120b"))
    assert provider.provider_name == "groq"


def test_groq_without_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_provider(Settings(llm_provider="groq", llm_api_key="", llm_model="openai/gpt-oss-120b"))


def test_provider_selection_is_case_insensitive() -> None:
    provider = get_llm_provider(Settings(llm_provider="FAKE"))
    assert isinstance(provider, FakeLLMProvider)
