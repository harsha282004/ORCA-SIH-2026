"""Structural tests for the Claude adapter — respx-mocked HTTP, never a
real API key or network call. This verifies request/response WIRING (the
forced tool-use mechanism is used correctly), not that Anthropic's real
API behaves as mocked here (see the module's own "NOT live-tested" note).
"""
from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import LLMConfigurationError, LLMRateLimitError, LLMResponseError
from app.llm.claude import ClaudeProvider

BASE_URL = "https://api.anthropic.com/v1/messages"


class _Schema(BaseModel):
    value: str


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        ClaudeProvider(api_key="", model="claude-x")


def test_missing_model_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        ClaudeProvider(api_key="k", model="")


@respx.mock
def test_generate_structured_parses_forced_tool_use_response() -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": "emit__schema", "input": {"value": "hello"}}]},
        )
    )
    provider = ClaudeProvider(api_key="k", model="claude-x", base_url=BASE_URL)
    result = provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert result == _Schema(value="hello")


@respx.mock
def test_rate_limit_response_raises_rate_limit_error() -> None:
    respx.post(BASE_URL).mock(return_value=httpx.Response(429, text="rate limited"))
    provider = ClaudeProvider(api_key="k", model="claude-x", base_url=BASE_URL)
    with pytest.raises(LLMRateLimitError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")


@respx.mock
def test_response_without_tool_use_block_raises_response_error_after_retry() -> None:
    respx.post(BASE_URL).mock(return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "oops"}]}))
    provider = ClaudeProvider(api_key="k", model="claude-x", base_url=BASE_URL)
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
