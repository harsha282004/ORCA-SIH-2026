"""LLM Provider Abstraction Layer — architecture.md §11a.

    LLM Intelligence Layer
            v
    LLM Provider Abstraction Layer   <-- this module
            v
    Configured LLM Provider

Every LLM-dependent component (Query Understanding, Evidence & Explanation
— architecture.md §10's own table marks these as the only two agents that
are "Real LLM agent? Yes") talks to `LLMProvider` only, never a vendor SDK
directly. Swapping `LLM_PROVIDER` in configuration never touches agent
code — see `app.llm.factory.get_llm_provider`.

architecture.md §11a's exact contract: `generate_structured(schema, prompt)
-> BaseModel`, `detect_language(text) -> str`. Both are implemented here as
the abstract interface every adapter (`claude.py`, `gemini.py`, `grok.py`,
`fake.py`) must satisfy identically.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProviderError(Exception):
    """Base for all LLM provider failures. Never silently swallowed —
    callers (Query Understanding, Evidence & Explanation) must convert
    this into a structured clarification/fallback state, never fabricate
    a result (architecture.md §38).
    """


class LLMConfigurationError(LLMProviderError):
    """Missing/invalid provider configuration — e.g. no API key, no model
    configured, or an unsupported LLM_PROVIDER value. Never retried (no
    amount of retrying fixes a missing key).
    """


class LLMTimeoutError(LLMProviderError):
    pass


class LLMRateLimitError(LLMProviderError):
    pass


class LLMResponseError(LLMProviderError):
    """The provider responded, but the response could not be parsed/
    validated into the requested structured schema."""


class LLMProvider(ABC):
    """architecture.md §11a's provider interface. `provider_name` is used
    only for logging/diagnostics — agent code must never branch on it.
    """

    provider_name: str

    @abstractmethod
    def generate_structured(self, *, schema: type[T], system_prompt: str, user_prompt: str) -> T:
        """Returns a validated instance of `schema`. Raises an
        `LLMProviderError` subclass on any failure (timeout, rate limit,
        malformed output, configuration error) — never returns
        unvalidated/partial data, and never silently substitutes a guess.
        """

    @abstractmethod
    def detect_language(self, text: str) -> str:
        """Returns an ISO 639-1 language code (e.g. "en", "hi", "kn")."""
