"""Structural tests for the Gemini adapter — respx-mocked HTTP only."""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import LLMConfigurationError, LLMResponseError
from app.llm.gemini import GeminiProvider, _strip_unsupported_keys

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class _Schema(BaseModel):
    value: str


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        GeminiProvider(api_key="", model="gemini-x")


@respx.mock
def test_generate_structured_parses_json_mode_response() -> None:
    respx.post(f"{BASE_URL}/gemini-x:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps({"value": "hello"})}]}}]},
        )
    )
    provider = GeminiProvider(api_key="k", model="gemini-x", base_url=BASE_URL)
    result = provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert result == _Schema(value="hello")


@respx.mock
def test_malformed_json_in_response_raises_response_error() -> None:
    respx.post(f"{BASE_URL}/gemini-x:generateContent").mock(
        return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    )
    provider = GeminiProvider(api_key="k", model="gemini-x", base_url=BASE_URL)
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")


def test_strip_unsupported_keys_removes_title_and_defs_recursively() -> None:
    schema = {
        "title": "Root",
        "$defs": {"x": {}},
        "properties": {"a": {"title": "A", "type": "string"}, "b": {"items": [{"title": "nested"}]}},
    }
    cleaned = _strip_unsupported_keys(schema)
    assert "title" not in cleaned
    assert "$defs" not in cleaned
    assert "title" not in cleaned["properties"]["a"]
    assert "title" not in cleaned["properties"]["b"]["items"][0]
