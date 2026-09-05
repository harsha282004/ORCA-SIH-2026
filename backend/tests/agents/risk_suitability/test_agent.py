"""Risk & Suitability Agent — architecture.md §10/§21/§22. Verifies this is
a THIN wrapper around Phase 2's real, unmodified Risk/Suitability engines
(no second formula, no second weight set) — Phase 5 task spec §15.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.gis.agent import GISGeofencingAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.models.contracts import AgentResult
from app.risk.config import get_risk_config
from app.risk.engine import compute_risk

NOW = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)

# Well inside the demo bbox, open water (matches tests/routing/test_api_route.py's OPEN_WATER_A).
OPEN_WATER_LAT, OPEN_WATER_LON = 12.80, 74.20


def _agent_result(*, data: dict, confidence: float = 0.9, status: str = "ok") -> AgentResult:
    return AgentResult(
        status=status,
        data=data,
        evidence=[],
        confidence=confidence,
        source_tier="live",
        timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [OPEN_WATER_LON, OPEN_WATER_LAT]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo",
        temporal_validity_status="VALID",
    )


def test_evaluate_reuses_the_real_phase2_risk_engine_exactly() -> None:
    weather = _agent_result(data={"wind_speed_10m": 5.0, "weathercode": 1})
    marine = _agent_result(data={"wave_height": 1.0})

    agent = RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())
    result = agent.evaluate(weather=weather, marine=marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON)

    assert result.status == "ok"
    # Recompute independently via the exact same engine call with the same
    # inputs the agent itself would have derived, and require an identical
    # score — proof there is no second, competing formula in the agent.
    from app.agents.common.risk_inputs import build_normalized_risk_components

    components = build_normalized_risk_components(
        weather, marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON, gis_agent=GISGeofencingAgent()
    )
    expected = compute_risk(components, get_risk_config().risk_weights, get_risk_config().risk_thresholds)
    assert result.risk_result.score == expected.score
    assert result.risk_result.level == expected.level


def test_missing_weather_status_failed_yields_insufficient_data() -> None:
    weather = _agent_result(data={}, status="failed")
    marine = _agent_result(data={"wave_height": 1.0})

    agent = RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())
    result = agent.evaluate(weather=weather, marine=marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON)

    assert result.status == "insufficient_data"
    assert result.risk_result is None
    assert result.reason is not None


def test_missing_required_parameter_yields_insufficient_data() -> None:
    weather = _agent_result(data={"weathercode": 1})  # wind_speed_10m missing
    marine = _agent_result(data={"wave_height": 1.0})

    agent = RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())
    result = agent.evaluate(weather=weather, marine=marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON)

    assert result.status == "insufficient_data"


def test_confidence_is_the_minimum_of_the_two_source_confidences() -> None:
    weather = _agent_result(data={"wind_speed_10m": 5.0, "weathercode": 1}, confidence=0.9)
    marine = _agent_result(data={"wave_height": 1.0}, confidence=0.4)

    agent = RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())
    result = agent.evaluate(weather=weather, marine=marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON)

    assert result.confidence == 0.4


def test_pfz_reference_is_passed_through_unavailable_by_default() -> None:
    weather = _agent_result(data={"wind_speed_10m": 5.0, "weathercode": 1})
    marine = _agent_result(data={"wave_height": 1.0})

    agent = RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())
    result = agent.evaluate(weather=weather, marine=marine, latitude=OPEN_WATER_LAT, longitude=OPEN_WATER_LON)

    assert result.suitability_result.pfz_reference.status == "unavailable"
