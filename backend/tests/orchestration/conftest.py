"""Shared offline test doubles for the orchestration test suite — no real
network, no real Redis, no real LLM API key anywhere in this package.

The GIS agent is left as the REAL `GISGeofencingAgent` (fixture geometry
only, no network — same choice `tests/routing/test_api_route.py` already
made) so boundary-check/safety behavior is genuinely exercised, not faked
away.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.query_understanding.agent import QueryUnderstandingAgent
from app.agents.query_understanding.models import RawIntentResult
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.llm.fake import FakeLLMProvider
from app.models.contracts import AgentResult
from app.orchestration.nodes import OrchestrationNodes

NOW = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)

# Well inside the demo bbox, open water fixture (matches tests/routing/test_api_route.py's OPEN_WATER_A).
OPEN_WATER_LAT, OPEN_WATER_LON = 12.80, 74.20


def make_weather_result(*, lat=OPEN_WATER_LAT, lon=OPEN_WATER_LON, wind_speed_10m=5.0, weathercode=1, confidence=0.9, status="ok") -> AgentResult:
    return AgentResult(
        status=status,
        data={} if status == "failed" else {"wind_speed_10m": wind_speed_10m, "weathercode": weathercode, "temperature_2m": 27.0},
        evidence=[],
        confidence=confidence,
        source_tier="live",
        timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo",
        temporal_validity_status="VALID",
    )


def make_marine_result(*, lat=OPEN_WATER_LAT, lon=OPEN_WATER_LON, wave_height=1.0, confidence=0.9, status="ok") -> AgentResult:
    return AgentResult(
        status=status,
        data={} if status == "failed" else {"wave_height": wave_height},
        evidence=[],
        confidence=confidence,
        source_tier="live",
        timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo",
        temporal_validity_status="VALID",
    )


class FakeWeatherAgent:
    def __init__(self, result: AgentResult | None = None):
        self._result = result or make_weather_result()

    def get_weather(self, *, latitude, longitude, requested_time=None):
        return self._result


class FakeOceanographicAgent:
    def __init__(self, result: AgentResult | None = None):
        self._result = result or make_marine_result()

    def get_marine(self, *, latitude, longitude, requested_time=None):
        return self._result


def make_raw_intent(**overrides) -> RawIntentResult:
    defaults = dict(
        language="en",
        intent_class="safety_check",
        activity="fishing",
        location_name=None,  # empty -> resolves to the full demo region, whose centroid is open water
        time_description="today",
        objective="is it safe to fish",
        requires_route=False,
        requires_pfz_reference=False,
        persona="fisherman",
        refers_to_prior=False,
        reference_type=None,
    )
    defaults.update(overrides)
    return RawIntentResult(**defaults)


def build_nodes(
    *,
    raw_intent: RawIntentResult | None = None,
    weather_result: AgentResult | None = None,
    marine_result: AgentResult | None = None,
    explanation_rationale: str = "Test explanation, grounded in nothing quantitative.",
) -> OrchestrationNodes:
    qu_agent = QueryUnderstandingAgent(llm_provider=FakeLLMProvider(structured_response=raw_intent or make_raw_intent()))
    evidence_agent = EvidenceExplanationAgent(
        llm_provider=FakeLLMProvider(structured_response=ExplanationOutput(rationale=explanation_rationale))
    )
    gis_agent = GISGeofencingAgent()
    return OrchestrationNodes(
        query_understanding_agent=qu_agent,
        weather_agent=FakeWeatherAgent(weather_result),
        oceanographic_agent=FakeOceanographicAgent(marine_result),
        gis_agent=gis_agent,
        risk_suitability_agent=RiskSuitabilityAgent(gis_agent=gis_agent),
        evidence_agent=evidence_agent,
    )


@pytest.fixture
def open_water_nodes() -> OrchestrationNodes:
    return build_nodes()
