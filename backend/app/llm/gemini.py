"""Google Gemini adapter — architecture.md §11a, one optional provider
implementation. Selected only when `LLM_PROVIDER=gemini`.

Implemented via a direct HTTPS call to the Generative Language API's
`generateContent` endpoint (`httpx`), using `generationConfig.responseSchema`
+ `responseMimeType=application/json` — Google's documented JSON-mode
mechanism for schema-constrained output. No `google-generativeai` SDK
dependency, same minimal-dependency rationale as `claude.py`.

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

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self, *, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 15.0):
        if not api_key:
            raise LLMConfigurationError("LLM_PROVIDER=gemini requires LLM_API_KEY to be set")
        if not model:
            raise LLMConfigurationError("LLM_PROVIDER=gemini requires LLM_MODEL to be set")
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
        url = f"{self._base_url}/{self._model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _strip_unsupported_keys(json_schema_for(schema)),
            },
        }

        try:
            response = httpx.post(
                url, params={"key": self._api_key}, json=payload, timeout=self._timeout_seconds
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"gemini request timed out after {self._timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"gemini request failed: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"gemini rate limit: {response.text[:300]}")
        if response.status_code >= 400:
            raise LLMProviderError(f"gemini returned HTTP {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return schema.model_validate(json.loads(text))
        except (ValueError, KeyError, IndexError, ValidationError) as exc:
            raise LLMResponseError(f"gemini response did not match {schema.__name__}: {exc}") from exc

    def detect_language(self, text: str) -> str:
        from pydantic import BaseModel

        class _LanguageDetection(BaseModel):
            language: str

        result = self.generate_structured(
            schema=_LanguageDetection,
            system_prompt="Detect the ISO 639-1 language code of the user's message. Respond only with the requested JSON.",
            user_prompt=text,
        )
        return result.language


def _strip_unsupported_keys(schema):
    """Gemini's `responseSchema` accepts a restricted subset of JSON Schema
    (no `$defs`/`title`/`additionalProperties` etc.). This is a best-effort
    recursive pass-through; the exact accepted subset is enforced live by
    Google's API — see the module docstring on why this is not
    live-verifiable here.
    """
    unsupported = {"title", "additionalProperties", "$defs", "definitions"}
    if isinstance(schema, dict):
        return {k: _strip_unsupported_keys(v) for k, v in schema.items() if k not in unsupported}
    if isinstance(schema, list):
        return [_strip_unsupported_keys(item) for item in schema]
    return schema
