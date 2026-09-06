"""Provider selection from `LLM_PROVIDER` config — architecture.md §11a.

This is the ONLY place that imports a specific provider adapter module by
name based on configuration. Agent code (`app.agents.query_understanding`,
`app.agents.evidence_explanation`) calls `get_llm_provider()` and never
imports `claude`/`gemini`/`grok`/`groq` directly — changing `LLM_PROVIDER`
in `.env` selects a different provider without touching agent code.

Note "grok" and "groq" are deliberately both present and are NOT the same
provider: "grok" (`app.llm.grok`) is xAI's Grok; "groq" (`app.llm.groq`)
is the unrelated Groq inference platform (e.g. `openai/gpt-oss-120b`).
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import LLMConfigurationError, LLMProvider

_SUPPORTED = ("claude", "gemini", "grok", "groq", "fake")


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider_name = (settings.llm_provider or "").strip().lower()

    if provider_name == "claude":
        from app.llm.claude import ClaudeProvider

        return ClaudeProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    if provider_name == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    if provider_name == "grok":
        from app.llm.grok import GrokProvider

        return GrokProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    if provider_name == "groq":
        from app.llm.groq import GroqProvider

        return GroqProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    if provider_name == "fake":
        # Not a real architecture.md §11a provider — a deliberate escape
        # hatch so a demo/dev environment can run the full orchestration
        # graph with zero API key, matching this project's existing
        # ORCA_MODE=demo philosophy. Never selected by default.
        from app.llm.fake import FakeLLMProvider

        return FakeLLMProvider()

    raise LLMConfigurationError(
        f"LLM_PROVIDER={settings.llm_provider!r} is not configured or not supported. "
        f"Set LLM_PROVIDER to one of: {', '.join(_SUPPORTED)}."
    )
