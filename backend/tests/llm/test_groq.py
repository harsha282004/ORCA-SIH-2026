"""Structural tests for the Groq adapter — respx-mocked HTTP only.

Groq (api.groq.com) is NOT xAI's Grok (api.x.ai) — see app/llm/groq.py's
module docstring. These tests are otherwise modeled directly on
test_grok.py's pattern, plus one test specific to Groq: that a 429 is
never retried (unlike every other adapter in this package), so a single
rate-limited call never silently becomes two requests against the API.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import LLMConfigurationError, LLMRateLimitError, LLMResponseError
from app.llm.groq import GroqProvider

BASE_URL = "https://api.groq.com/openai/v1/chat/completions"


class _Schema(BaseModel):
    value: str


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        GroqProvider(api_key="", model="openai/gpt-oss-120b")


def test_missing_model_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        GroqProvider(api_key="k", model="")


@respx.mock
def test_generate_structured_parses_json_object_response() -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"value": "hello"})}}]})
    )
    provider = GroqProvider(api_key="k", model="openai/gpt-oss-120b", base_url=BASE_URL)
    result = provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert result == _Schema(value="hello")


@respx.mock
def test_malformed_json_content_raises_response_error() -> None:
    respx.post(BASE_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    provider = GroqProvider(api_key="k", model="openai/gpt-oss-120b", base_url=BASE_URL)
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")


@respx.mock
def test_server_error_raises_provider_error_after_retry() -> None:
    route = respx.post(BASE_URL).mock(return_value=httpx.Response(500, text="internal error"))
    provider = GroqProvider(api_key="k", model="openai/gpt-oss-120b", base_url=BASE_URL)
    with pytest.raises(Exception):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    # A genuine transient server error still gets the existing single retry.
    assert route.call_count == 2


@respx.mock
def test_rate_limit_is_never_retried() -> None:
    """The critical Groq-specific behavior: unlike every other adapter in
    this package, a 429 must not trigger the generic retry-once — it
    already told us to back off, so retrying immediately after a fixed 1s
    backoff would only double the wasted request against an already-
    throttled key (the exact failure mode identified auditing Gemini).
    """
    route = respx.post(BASE_URL).mock(return_value=httpx.Response(429, text='{"error": "rate limited"}'))
    provider = GroqProvider(api_key="k", model="openai/gpt-oss-120b", base_url=BASE_URL)
    with pytest.raises(LLMRateLimitError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert route.call_count == 1
