"""Structural tests for the Grok adapter — respx-mocked HTTP only."""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import LLMConfigurationError, LLMResponseError
from app.llm.grok import GrokProvider

BASE_URL = "https://api.x.ai/v1/chat/completions"


class _Schema(BaseModel):
    value: str


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        GrokProvider(api_key="", model="grok-x")


@respx.mock
def test_generate_structured_parses_json_object_response() -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"value": "hello"})}}]}
        )
    )
    provider = GrokProvider(api_key="k", model="grok-x", base_url=BASE_URL)
    result = provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert result == _Schema(value="hello")


@respx.mock
def test_malformed_json_content_raises_response_error() -> None:
    respx.post(BASE_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    provider = GrokProvider(api_key="k", model="grok-x", base_url=BASE_URL)
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")


@respx.mock
def test_server_error_raises_provider_error_after_retry() -> None:
    respx.post(BASE_URL).mock(return_value=httpx.Response(500, text="internal error"))
    provider = GrokProvider(api_key="k", model="grok-x", base_url=BASE_URL)
    with pytest.raises(Exception):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
