"""Anthropic Claude adapter — architecture.md §11a: "one optional
implementation among several... zero statements elsewhere in this document
requiring Anthropic/Claude specifically for ORCA to function." Selected
only when `LLM_PROVIDER=claude`.

Implemented via a direct HTTPS call to Anthropic's Messages API (`httpx`,
already a project dependency) rather than the `anthropic` SDK — keeps
installed dependencies minimal, consistent with earlier phases' "no LLM
provider SDKs unless required" discipline, and keeps this adapter no more
privileged than `grok.py`/`gemini.py`.

Structured output is obtained via forced tool-use: a single synthetic tool
whose `input_schema` is the target Pydantic model's JSON schema, with
`tool_choice` forcing that exact tool — Anthropic's documented mechanism
for schema-constrained output.

**NOT live-tested in this environment** — no `LLM_API_KEY` is configured
here. See docs/orchestration.md for what was and wasn't validated.
"""
from __future__ import annotations

import httpx
from pydantic import ValidationError

from app.llm.base import (
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.provider import json_schema_for, retry_once_with_backoff

DEFAULT_BASE_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


class ClaudeProvider(LLMProvider):
    provider_name = "claude"

    def __init__(self, *, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 15.0):
        if not api_key:
            raise LLMConfigurationError("LLM_PROVIDER=claude requires LLM_API_KEY to be set")
        if not model:
            raise LLMConfigurationError("LLM_PROVIDER=claude requires LLM_MODEL to be set")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    def generate_structured(self, *, schema, system_prompt, user_prompt):
        return retry_once_with_backoff(
            lambda: self._call_once(schema=schema, system_prompt=system_prompt, user_prompt=user_prompt),
            non_retryable=(LLMConfigurationError,),
        )

    def _call_once(self, *, schema, system_prompt, user_prompt):
        tool_name = f"emit_{schema.__name__.lower()}"
        payload = {
            "model": self._model,
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": [
                {
                    "name": tool_name,
                    "description": f"Emit a single {schema.__name__} object matching the given schema exactly.",
                    "input_schema": json_schema_for(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        try:
            response = httpx.post(self._base_url, json=payload, headers=headers, timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"claude request timed out after {self._timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"claude request failed: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"claude rate limit: {response.text[:300]}")
        if response.status_code >= 400:
            raise LLMProviderError(f"claude returned HTTP {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
            tool_blocks = [block for block in body.get("content", []) if block.get("type") == "tool_use"]
            if not tool_blocks:
                raise LLMResponseError("claude response contained no tool_use block")
            return schema.model_validate(tool_blocks[0]["input"])
        except (ValueError, KeyError, ValidationError) as exc:
            raise LLMResponseError(f"claude response did not match {schema.__name__}: {exc}") from exc

    def detect_language(self, text: str) -> str:
        from pydantic import BaseModel

        class _LanguageDetection(BaseModel):
            language: str

        result = self.generate_structured(
            schema=_LanguageDetection,
            system_prompt="Detect the ISO 639-1 language code of the user's message. Respond only via the tool call.",
            user_prompt=text,
        )
        return result.language
