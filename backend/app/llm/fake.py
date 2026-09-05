"""Deterministic test double for `LLMProvider` — Phase 5 task spec §30.

Powers the entire automated test suite; makes zero network calls, requires
no API key. Not a "provider" in the architecture.md §11a sense (it is
never a valid `LLM_PROVIDER` selection for a real deployment) — it exists
purely so Query Understanding / Evidence & Explanation / orchestration
tests never depend on a live LLM API.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.llm.base import LLMProvider, LLMResponseError


class FakeLLMProvider(LLMProvider):
    provider_name = "fake"

    def __init__(
        self,
        *,
        structured_response: BaseModel | None = None,
        structured_responses: dict[str, BaseModel] | None = None,
        language: str = "en",
        fail_with: Exception | None = None,
    ):
        self._default_response = structured_response
        self._responses_by_schema = structured_responses or {}
        self._language = language
        self._fail_with = fail_with
        self.calls: list[dict] = []

    def generate_structured(self, *, schema, system_prompt, user_prompt):
        self.calls.append({"schema": schema.__name__, "system_prompt": system_prompt, "user_prompt": user_prompt})

        if self._fail_with is not None:
            raise self._fail_with

        response = self._responses_by_schema.get(schema.__name__, self._default_response)
        if response is None:
            raise LLMResponseError(f"FakeLLMProvider has no configured response for schema {schema.__name__}")
        if not isinstance(response, schema):
            raise LLMResponseError(
                f"FakeLLMProvider configured response is {type(response).__name__}, expected {schema.__name__}"
            )
        return response

    def detect_language(self, text: str) -> str:
        del text
        if self._fail_with is not None:
            raise self._fail_with
        return self._language
