"""Query Understanding Agent — architecture.md §10, §12, §30, §31a.

The first (and one of only two — the other being Evidence & Explanation)
agent permitted to call an LLM (architecture.md §10's table). Its job is
NOT to answer the user — it converts natural language into a strictly
validated `IntentResult`, or a structured `ClarificationNeeded`. It never
decides safety, never computes risk, never fabricates coordinates or
observations (Phase 5 task spec §10).

    query -> LLM (RawIntentResult, no coordinates/absolute timestamps)
          -> deterministic location resolution (location.py)
          -> deterministic time-window resolution (time_resolution.py)
          -> IntentResult | ClarificationNeeded
"""
from __future__ import annotations

from datetime import datetime

from app.agents.query_understanding.location import resolve_location
from app.agents.query_understanding.models import ClarificationNeeded, IntentResult, RawIntentResult
from app.agents.query_understanding.time_resolution import resolve_time_window
from app.config import Settings, get_settings
from app.i18n.languages import SUPPORTED_LANGUAGES
from app.llm.base import LLMProvider, LLMProviderError
from app.llm.factory import get_llm_provider
from app.models.geo import BBox

_SYSTEM_PROMPT = """You are ORCA's Query Understanding component for a marine-safety \
assistant serving fishermen, researchers, coastal authorities, and maritime operators \
in the Mangaluru-Udupi coastal Karnataka region of India.

Extract structured intent from the user's query. You MUST:
- Detect the language of the query (ISO 639-1 code).
- Classify the intent into exactly one of: safety_check, zone_recommendation, \
route_planning, diagnostic_exploration, boundary_check.
- Extract any place name mentioned, as plain text only (e.g. "Mangaluru") — \
never invent latitude/longitude coordinates.
- Extract any time reference as plain text only (e.g. "tomorrow morning") — \
never invent an absolute date/time yourself.
- Set requires_route=true only if the user is explicitly asking for a route, \
path, or navigation plan.
- Set requires_pfz_reference=true only if the user asks about official \
Potential Fishing Zones.
- Infer the persona (fisherman, researcher, authority, operator) from context; \
default to fisherman if unclear.
- Set refers_to_prior=true only if the query is clearly a follow-up to a \
previous turn (e.g. "what about Friday?").

You compute NOTHING about risk, safety, or weather. You only extract structure."""


class QueryUnderstandingAgent:
    def __init__(self, *, llm_provider: LLMProvider | None = None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._llm_provider = llm_provider or get_llm_provider(self._settings)

    def understand(
        self,
        *,
        query: str,
        now: datetime | None = None,
        demo_bbox: BBox | None = None,
    ) -> IntentResult | ClarificationNeeded:
        if not query or not query.strip():
            return ClarificationNeeded(reason="empty query", missing_fields=["query"], original_query=query)

        demo_bbox = demo_bbox or self._settings.demo_bbox

        try:
            raw = self._llm_provider.generate_structured(
                schema=RawIntentResult, system_prompt=_SYSTEM_PROMPT, user_prompt=query
            )
        except LLMProviderError as exc:
            # architecture.md §38: never a fabricated intent, never a bypass
            # of deterministic safety checks — a structured failure instead.
            return ClarificationNeeded(
                reason=f"could not understand the query: {exc}", missing_fields=[], original_query=query
            )

        if raw.language not in SUPPORTED_LANGUAGES:
            return ClarificationNeeded(
                reason=f"unsupported language: {raw.language!r} (ORCA currently supports English, Hindi, and Kannada)",
                missing_fields=["language"],
                original_query=query,
            )

        location = resolve_location(raw.location_name, demo_bbox=demo_bbox)
        if location is None:
            return ClarificationNeeded(
                reason=f"location {raw.location_name!r} is not within the supported Mangaluru-Udupi demo region",
                missing_fields=["location"],
                original_query=query,
            )

        time_window = resolve_time_window(raw.time_description, now=now)

        return IntentResult(
            language=raw.language,
            intent_class=raw.intent_class,
            activity=raw.activity,
            location=location,
            time_window=time_window,
            objective=raw.objective,
            constraints={},
            requires_route=raw.requires_route,
            requires_pfz_reference=raw.requires_pfz_reference,
            persona=raw.persona,
            refers_to_prior=raw.refers_to_prior,
            reference_type=raw.reference_type,
        )
