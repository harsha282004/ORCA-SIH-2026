"""xAI Grok adapter — architecture.md §11a, one optional provider
implementation. Selected only when `LLM_PROVIDER=grok`.

xAI's API is OpenAI-compatible (`chat/completions`). Structured output is
requested via `response_format={"type": "json_object"}` plus the target
schema described in the system prompt, then validated with Pydantic —
the broadly-compatible approach that doesn't depend on the newest
strict-JSON-schema feature actually being available for a given model.
No `openai`/xAI SDK dependency, same minimal-dependency rationale as
`claude.py`/`gemini.py`.

**NOT live-tested in this environment** — no `LLM_API_KEY` is configured
here.
"""
from __future__ import annotations

import json

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

DEFAULT_BASE_URL = "https://api.x.ai/v1/chat/completions"


class GrokProvider(LLMProvider):
    provider_name = "grok"

    def __init__(self, *, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 15.0):
        if not api_key:
            raise LLMConfigurationError("LLM_PROVIDER=grok requires LLM_API_KEY to be set")
        if not model:
            raise LLMConfigurationError("LLM_PROVIDER=grok requires LLM_MODEL to be set")
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
        schema_instructions = (
            f"{system_prompt}\n\nRespond with a single JSON object matching exactly this JSON Schema "
            f"(no prose, no markdown fences):\n{json.dumps(json_schema_for(schema))}"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": schema_instructions},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "content-type": "application/json"}

        try:
            response = httpx.post(self._base_url, json=payload, headers=headers, timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"grok request timed out after {self._timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"grok request failed: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"grok rate limit: {response.text[:300]}")
        if response.status_code >= 400:
            raise LLMProviderError(f"grok returned HTTP {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return schema.model_validate(json.loads(content))
        except (ValueError, KeyError, IndexError, ValidationError) as exc:
            raise LLMResponseError(f"grok response did not match {schema.__name__}: {exc}") from exc

    def detect_language(self, text: str) -> str:
        from pydantic import BaseModel

        class _LanguageDetection(BaseModel):
            language: str

        result = self.generate_structured(
            schema=_LanguageDetection,
            system_prompt="Detect the ISO 639-1 language code of the user's message.",
            user_prompt=text,
        )
        return result.language
