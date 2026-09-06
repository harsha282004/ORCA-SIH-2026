"""Groq adapter — architecture.md §11a, one optional provider
implementation. Selected only when `LLM_PROVIDER=groq`.

NOT to be confused with `grok.py` (xAI's "Grok" model) — Groq is a
different company entirely, an inference platform serving open models
(e.g. `openai/gpt-oss-120b`) through an OpenAI-compatible
`chat/completions` endpoint. The two names are easy to conflate; this
module is deliberately named/commented to make the distinction explicit
everywhere it matters.

Because Groq's API is OpenAI-compatible (same `chat/completions` request/
response shape, same `response_format={"type": "json_object"}` JSON mode,
same bearer-token auth) this adapter reuses `grok.py`'s exact, already-
proven request pattern — schema described in the system prompt, then
validated with Pydantic — rather than inventing a new one. No `openai`/
Groq SDK dependency, same minimal-dependency rationale as every other
adapter in this package.

Rate-limit handling (architecture.md §38's "retry once w/ backoff" is a
general default, not an unconditional one): unlike the other adapters in
this package, `LLMRateLimitError` is explicitly excluded from the retry
here. A 429 means the provider just said "stop briefly" — retrying it
after a fixed 1s backoff (`retry_once_with_backoff`'s default) almost
never clears a genuine rate/quota window and only doubles the wasted
request against an already-throttled key. Genuine transient failures
(timeout, malformed response, a 5xx) still get the existing single retry.
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

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    provider_name = "groq"

    def __init__(self, *, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 15.0):
        if not api_key:
            raise LLMConfigurationError("LLM_PROVIDER=groq requires LLM_API_KEY to be set")
        if not model:
            raise LLMConfigurationError("LLM_PROVIDER=groq requires LLM_MODEL to be set")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    def generate_structured(self, *, schema, system_prompt, user_prompt):
        return retry_once_with_backoff(
            lambda: self._call_once(schema=schema, system_prompt=system_prompt, user_prompt=user_prompt),
            # LLMRateLimitError is deliberately non-retryable here — see
            # the module docstring. LLMConfigurationError never made sense
            # to retry either (no amount of waiting adds a missing key).
            non_retryable=(LLMConfigurationError, LLMRateLimitError),
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
            raise LLMTimeoutError(f"groq request timed out after {self._timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"groq request failed: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"groq rate limit: {response.text[:300]}")
        if response.status_code >= 400:
            raise LLMProviderError(f"groq returned HTTP {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return schema.model_validate(json.loads(content))
        except (ValueError, KeyError, IndexError, ValidationError) as exc:
            raise LLMResponseError(f"groq response did not match {schema.__name__}: {exc}") from exc

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
