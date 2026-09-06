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
from app.i18n.detect import detect_script_language
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
- For a route_planning query naming TWO places (e.g. "from Mangaluru to Udupi", \
"a route from X to Y"), set location_name to the ORIGIN place and \
destination_name to the DESTINATION place — both plain text only, never \
coordinates. Leave destination_name unset for every other intent, and for a \
route_planning query that only names one place or none.
- Extract any time reference as plain text only (e.g. "tomorrow morning") — \
never invent an absolute date/time yourself.
- Set requires_route=true only if the user is explicitly asking for a route, \
path, or navigation plan.
- Set requires_pfz_reference=true only if the user asks about official \
Potential Fishing Zones.
- Infer the persona (fisherman, researcher, authority, operator) from context; \
default to fisherman if unclear.
- Set refers_to_prior=true only if the query is clearly a follow-up to a \
previous turn — it does NOT name its own place/full question, it refers back with \
a pronoun or an implicit "the same thing, but...". Examples in English: "what \
about Friday?", "is it still safe?", "what about the waves there?", "which is \
safer?", "what about the alternative?". The SAME patterns apply in Hindi/Kannada \
using their own pronouns/particles — e.g. Hindi "वहाँ की स्थिति कैसी है?" ("how are \
conditions THERE?"), "क्या यह अभी भी सुरक्षित है?" ("is it STILL safe?"); Kannada \
"ಅಲ್ಲಿ ಅಲೆಗಳ ಪರಿಸ್ಥಿತಿ ಹೇಗಿದೆ?" ("how are the wave conditions THERE?"), "ಅದು ಇನ್ನೂ \
ಸುರಕ್ಷಿತವೇ?" ("is IT still safe?") — recognize the SAME referring-back structure \
regardless of language; do not require an English cue word. When refers_to_prior \
is true, also set reference_type: "same_query_different_param" if the user is \
asking to re-run the same kind of question with one parameter changed (e.g. a \
different distance, place, or time), or "follow_up_explanation" if they are \
asking to explain/clarify the previous answer itself, rather than re-run anything.
- If refers_to_prior=true, reference_type="same_query_different_param", AND the \
requested change is specifically about distance from shore (e.g. "what about \
20 km further offshore?"), set reference_delta.offshore_distance_km to that \
distance in kilometers (positive = farther offshore). Leave reference_delta \
unset for every other kind of change — you name the requested distance only; \
you never compute or state the resulting coordinate yourself.
- If refers_to_prior=true AND the user is asking to compare previously-returned \
options (e.g. "which is safer?", "compare them", "which one is better?"), set \
operation="compare". Otherwise leave operation unset (it defaults to a fresh \
evaluation) — do NOT set operation="compare" for a first-turn query with nothing \
to compare yet.
- If refers_to_prior=true AND the user is clearly asking about a SPECIFIC \
previously-returned option, set selection_reference: "primary" for the one \
already recommended/selected (e.g. "what about the waves there?", "is it still \
safe?"), or "alternative" for a DIFFERENT one that was also offered but not \
selected (e.g. "what about the other route?", "what about the second option?", \
"tell me about Route B instead"). Leave selection_reference unset if the query \
does not clearly point at one specific previously-returned option.
- You never invent WHICH candidate/route "primary" or "alternative" refers to \
beyond this relative label — deterministic code resolves the actual location/\
route from conversation state.
- Set is_scenario=true for a WHAT-IF question — the user is asking what would \
happen if some condition were different, not what it currently/actually is. \
Examples: "what if wave height increases to 3.5 metres?", "what happens if wind \
becomes 15 m/s?", "would it still be safe if waves reach 3 metres?". If the \
scenario names a supported variable (wave height or wind speed) with an \
explicit NUMBER and unit, also set scenario_variable ("wave_height" or \
"wind_speed") and scenario_target_value to that number converted to metres \
(wave height) or metres/second (wind speed) — e.g. "15 knots" you may convert \
using 1 knot = 0.514 m/s, but NEVER invent a number the user did not state. If \
the scenario names an unsupported variable (fish, catch, population, \
chlorophyll, "the ocean becomes dangerous" with no number) or gives no explicit \
number, leave scenario_variable/scenario_target_value unset — deterministic code \
will ask the user for a supported, numeric scenario rather than guessing one.
- Set wants_temporal_window=true when the user is asking about a RANGE of times \
or which of several times is best/safer/better — e.g. "when is the best time to \
fish tomorrow?", "compare morning and afternoon", "which is safer, 6am or \
noon?", "how does the afternoon compare with the morning?". Leave it false for \
an ordinary single-instant question ("is it safe to fish tomorrow morning?" \
alone is still a single instant/window, not a comparison, unless the user is \
explicitly asking you to compare or pick the best time within it).

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

        # Phase 6 §6: a deterministic, script-based cross-check on the LLM's
        # own language field — never a second LLM call (see
        # app.i18n.detect's module docstring for why `LLMProvider
        # .detect_language()` stays unused). Script identification for
        # Devanagari/Kannada/Tamil/Telugu/Malayalam is essentially
        # unambiguous, so a confident deterministic result (non-`None`)
        # overrides whatever ISO code the LLM guessed — catching real,
        # observed mis-labeling from a smaller open model without adding a
        # network round-trip.
        detected_script_language = detect_script_language(query)
        if detected_script_language is not None and detected_script_language != raw.language:
            raw = raw.model_copy(update={"language": detected_script_language})

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

        # Phase 5 (task §28): the SAME deterministic gazetteer resolution
        # `location_name` already uses, applied to `destination_name` when
        # the LLM named one (route_planning with two places). A named-but-
        # unrecognized destination asks for clarification exactly like an
        # unrecognized origin — never silently dropped or guessed.
        destination = None
        if raw.destination_name:
            destination = resolve_location(raw.destination_name, demo_bbox=demo_bbox)
            if destination is None:
                return ClarificationNeeded(
                    reason=f"destination {raw.destination_name!r} is not within the supported Mangaluru-Udupi demo region",
                    missing_fields=["destination"],
                    original_query=query,
                )

        time_window = resolve_time_window(raw.time_description, now=now)

        return IntentResult(
            language=raw.language,
            intent_class=raw.intent_class,
            activity=raw.activity,
            location=location,
            destination=destination,
            time_window=time_window,
            objective=raw.objective,
            constraints={},
            requires_route=raw.requires_route,
            requires_pfz_reference=raw.requires_pfz_reference,
            persona=raw.persona,
            refers_to_prior=raw.refers_to_prior,
            reference_type=raw.reference_type,
            reference_delta=raw.reference_delta,
            operation=raw.operation,
            selection_reference=raw.selection_reference,
            is_scenario=raw.is_scenario,
            scenario_variable=raw.scenario_variable,
            scenario_target_value=raw.scenario_target_value,
            wants_temporal_window=raw.wants_temporal_window,
        )
