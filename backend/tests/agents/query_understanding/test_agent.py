"""Query Understanding Agent — architecture.md §10/§12/§30/§31a. Every test
uses `FakeLLMProvider`; zero network/API-key dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.query_understanding.agent import QueryUnderstandingAgent
from app.agents.query_understanding.models import ClarificationNeeded, IntentResult, RawIntentResult
from app.llm.base import LLMResponseError
from app.llm.fake import FakeLLMProvider
from app.models.geo import BBox

DEMO_BBOX = BBox(min_lat=12.70, min_lon=73.50, max_lat=13.45, max_lon=75.05)
NOW = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)


def _raw(**overrides) -> RawIntentResult:
    defaults = dict(
        language="en",
        intent_class="safety_check",
        activity="fishing",
        location_name="Mangaluru",
        time_description="tomorrow morning",
        objective="is it safe to fish",
        requires_route=False,
        requires_pfz_reference=False,
        persona="fisherman",
        refers_to_prior=False,
        reference_type=None,
    )
    defaults.update(overrides)
    return RawIntentResult(**defaults)


def test_understand_returns_intent_result_for_a_well_formed_query() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw()))
    result = agent.understand(query="Is it safe to go fishing near Mangaluru tomorrow morning?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, IntentResult)
    assert result.location["type"] == "named_place"
    assert result.time_window["start"].startswith("2026-09-06")


def test_understand_works_for_hindi_language_code() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw(language="hi")))
    result = agent.understand(query="क्या कल सुबह मछली पकड़ना सुरक्षित है?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, IntentResult)
    assert result.language == "hi"


def test_understand_works_for_kannada_language_code() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw(language="kn")))
    result = agent.understand(query="ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮೀನುಗಾರಿಕೆ ಸುರಕ್ಷಿತವೇ?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, IntentResult)
    assert result.language == "kn"


def test_unsupported_language_returns_clarification() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw(language="fr")))
    result = agent.understand(query="est-ce sûr?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, ClarificationNeeded)
    assert "language" in result.missing_fields


def test_ambiguous_unrecognized_location_returns_clarification_not_a_guess() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw(location_name="Atlantis")))
    result = agent.understand(query="Is it safe near Atlantis?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, ClarificationNeeded)
    assert "location" in result.missing_fields


def test_empty_query_returns_clarification_without_calling_the_llm() -> None:
    provider = FakeLLMProvider(structured_response=_raw())
    agent = QueryUnderstandingAgent(llm_provider=provider)
    result = agent.understand(query="   ", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, ClarificationNeeded)
    assert provider.calls == []


def test_llm_provider_failure_returns_clarification_not_a_crash() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(fail_with=LLMResponseError("malformed output")))
    result = agent.understand(query="Is it safe to fish?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, ClarificationNeeded)


def test_raw_intent_schema_has_no_coordinate_or_absolute_timestamp_fields() -> None:
    # Structural guarantee, not a runtime check: the LLM-facing schema
    # cannot express a coordinate or an absolute timestamp at all.
    fields = RawIntentResult.model_fields.keys()
    assert not any("lat" in f or "lon" in f or "coord" in f for f in fields)
    assert "location_name" in fields
    assert "time_description" in fields


def test_location_and_time_window_are_never_copied_verbatim_from_the_llm() -> None:
    agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=_raw()))
    result = agent.understand(query="Is it safe near Mangaluru tomorrow morning?", now=NOW, demo_bbox=DEMO_BBOX)
    assert isinstance(result, IntentResult)
    # location/time_window are dicts built by deterministic post-processing
    # (location.py / time_resolution.py), never raw LLM string fields.
    assert isinstance(result.location, dict) and "resolved_bbox" in result.location
    assert isinstance(result.time_window, dict) and "start" in result.time_window and "end" in result.time_window
