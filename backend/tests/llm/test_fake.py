"""FakeLLMProvider — Phase 5 task spec §30: powers the entire test suite,
never makes a network call.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.base import LLMResponseError
from app.llm.fake import FakeLLMProvider


class _Schema(BaseModel):
    value: str


class _OtherSchema(BaseModel):
    other: int


def test_returns_configured_default_response() -> None:
    provider = FakeLLMProvider(structured_response=_Schema(value="hello"))
    result = provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert result == _Schema(value="hello")


def test_returns_per_schema_response() -> None:
    provider = FakeLLMProvider(structured_responses={"_Schema": _Schema(value="a"), "_OtherSchema": _OtherSchema(other=1)})
    assert provider.generate_structured(schema=_Schema, system_prompt="s", user_prompt="u") == _Schema(value="a")
    assert provider.generate_structured(schema=_OtherSchema, system_prompt="s", user_prompt="u") == _OtherSchema(other=1)


def test_records_every_call() -> None:
    provider = FakeLLMProvider(structured_response=_Schema(value="hello"))
    provider.generate_structured(schema=_Schema, system_prompt="sys", user_prompt="user")
    assert len(provider.calls) == 1
    assert provider.calls[0]["schema"] == "_Schema"


def test_raises_when_no_response_configured_for_schema() -> None:
    provider = FakeLLMProvider()
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="s", user_prompt="u")


def test_raises_when_configured_response_is_wrong_schema() -> None:
    provider = FakeLLMProvider(structured_response=_OtherSchema(other=1))
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="s", user_prompt="u")


def test_fail_with_raises_on_generate_structured() -> None:
    provider = FakeLLMProvider(fail_with=LLMResponseError("boom"))
    with pytest.raises(LLMResponseError):
        provider.generate_structured(schema=_Schema, system_prompt="s", user_prompt="u")


def test_fail_with_raises_on_detect_language() -> None:
    provider = FakeLLMProvider(fail_with=LLMResponseError("boom"))
    with pytest.raises(LLMResponseError):
        provider.detect_language("hello")


def test_detect_language_returns_configured_language() -> None:
    provider = FakeLLMProvider(language="hi")
    assert provider.detect_language("some text") == "hi"
