"""Shared provider abstractions — `json_schema_for`, `retry_once_with_backoff`."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.provider import json_schema_for, retry_once_with_backoff


class _Schema(BaseModel):
    value: str


def test_json_schema_for_returns_pydantic_schema() -> None:
    schema = json_schema_for(_Schema)
    assert schema["properties"]["value"]["type"] == "string"


def test_retry_once_succeeds_on_first_try() -> None:
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert retry_once_with_backoff(fn, backoff_seconds=0) == "ok"
    assert len(calls) == 1


def test_retry_once_retries_after_one_failure_then_succeeds() -> None:
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return "ok"

    assert retry_once_with_backoff(fn, backoff_seconds=0) == "ok"
    assert len(calls) == 2


def test_retry_once_raises_after_second_failure() -> None:
    def fn():
        raise RuntimeError("still failing")

    with pytest.raises(RuntimeError):
        retry_once_with_backoff(fn, backoff_seconds=0)


def test_non_retryable_exception_is_never_retried() -> None:
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("config error")

    with pytest.raises(ValueError):
        retry_once_with_backoff(fn, backoff_seconds=0, non_retryable=(ValueError,))
    assert len(calls) == 1
