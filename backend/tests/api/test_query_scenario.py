"""Phase 7 — conversational what-if scenarios (`_handle_scenario_query` in
`app.api.v1.query`). Pure unit tests: hand-built `OrchestrationState`/
`SessionState`, a real (network-free, fixture-only) `GISGeofencingAgent`/
`RiskSuitabilityAgent`, `FakeLLMProvider`-backed `EvidenceExplanationAgent`
— no live network, no graph invocation (covered separately by
tests/orchestration and tests/api/test_query.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.query_understanding.models import IntentResult
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.api.v1.query import _handle_scenario_query
from app.llm.fake import FakeLLMProvider
from app.models.contracts import AgentResult
from app.orchestration.state import OrchestrationState
from app.risk.config import get_risk_config
from app.session.models import SessionState

NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
OPEN_WATER = (12.80, 74.20)


def _agent_result(*, data: dict, status: str = "ok", temporal_validity_status: str = "VALID") -> AgentResult:
    lat, lon = OPEN_WATER
    return AgentResult(
        status=status, data=data, evidence=[], confidence=0.9, source_tier="live", timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo", temporal_validity_status=temporal_validity_status,
    )


def _intent(**overrides) -> IntentResult:
    lat, lon = OPEN_WATER
    defaults = dict(
        language="en", intent_class="safety_check", activity="fishing",
        location={"type": "named_place", "name": "Area A", "resolved_bbox": {"min_lat": lat - 0.03, "min_lon": lon - 0.03, "max_lat": lat + 0.03, "max_lon": lon + 0.03}},
        destination=None, time_window={"start": NOW.isoformat(), "end": NOW.isoformat()},
        objective="what if", constraints={}, requires_route=False, requires_pfz_reference=False, persona="fisherman",
        refers_to_prior=True, reference_type="same_query_different_param",
        is_scenario=True, scenario_variable=None, scenario_target_value=None, wants_temporal_window=False,
    )
    defaults.update(overrides)
    return IntentResult(**defaults)


def _state(*, intent, weather=None, marine=None) -> OrchestrationState:
    return OrchestrationState(
        query="what if?", intent=intent, language=intent.language,
        weather=weather or _agent_result(data={"wind_speed_10m": 4.0, "weathercode": 1}),
        marine=marine or _agent_result(data={"wave_height": 0.6}),
        latitude=OPEN_WATER[0], longitude=OPEN_WATER[1],
    )


def _evidence_agent(rationale: str = "Scenario explanation.") -> EvidenceExplanationAgent:
    return EvidenceExplanationAgent(llm_provider=FakeLLMProvider(structured_response=ExplanationOutput(rationale=rationale)))


def _call(state, session=None):
    return _handle_scenario_query(
        final_state=state, session=session or SessionState(), evidence_agent=_evidence_agent(),
        gis_agent=GISGeofencingAgent(), risk_suitability_agent=RiskSuitabilityAgent(), risk_config=get_risk_config(),
    )


def test_returns_none_when_not_a_scenario_query() -> None:
    state = _state(intent=_intent(is_scenario=False))
    assert _call(state) is None


def test_underspecified_scenario_asks_for_clarification_not_a_guess() -> None:
    state = _state(intent=_intent(is_scenario=True, scenario_variable=None, scenario_target_value=None))
    response = _call(state)
    assert response is not None
    assert response.data["scenario"] is None
    assert "wave height" in response.data["explanation"].lower()


def test_wave_height_scenario_recalculates_deterministic_risk() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wave_height", scenario_target_value=3.5),
        marine=_agent_result(data={"wave_height": 0.6}),
    )
    response = _call(state)
    assert response is not None
    scenario = response.data["scenario"]
    assert scenario["baseline_value"] == 0.6
    assert scenario["scenario_value"] == 3.5
    assert scenario["delta"] == 3.5 - 0.6
    assert scenario["label"] == "SIMULATION — NOT LIVE DATA"
    # A jump from calm (0.6m) to a saturating 3.5m must raise risk.
    assert scenario["risk_score_delta"] > 0
    assert scenario["baseline"]["decision"]["outcome"] == "RECOMMEND"
    assert scenario["scenario_result"]["decision"]["outcome"] != "RECOMMEND"
    assert scenario["decision_changed"] is True


def test_wind_speed_scenario_recalculates_deterministic_risk() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wind_speed", scenario_target_value=25.0),
        weather=_agent_result(data={"wind_speed_10m": 3.0, "weathercode": 1}),
    )
    response = _call(state)
    scenario = response.data["scenario"]
    assert scenario["baseline_value"] == 3.0
    assert scenario["scenario_value"] == 25.0
    assert scenario["risk_score_delta"] > 0


def test_scenario_baseline_is_never_mutated_by_the_perturbation() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wave_height", scenario_target_value=3.5),
        marine=_agent_result(data={"wave_height": 0.6}),
    )
    response = _call(state)
    baseline_risk = response.data["scenario"]["baseline"]["risk_suitability"]["risk_result"]["score"]
    scenario_risk = response.data["scenario"]["scenario_result"]["risk_suitability"]["risk_result"]["score"]
    assert baseline_risk != scenario_risk
    assert baseline_risk < scenario_risk


def test_stale_baseline_data_refuses_scenario_assessment() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wave_height", scenario_target_value=3.5),
        marine=_agent_result(data={"wave_height": 0.6}, temporal_validity_status="STALE"),
    )
    response = _call(state)
    assert response.data["scenario"] is None
    assert "stale" in response.data["explanation"].lower()


def test_missing_baseline_variable_is_reported_not_fabricated() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wave_height", scenario_target_value=3.5),
        marine=_agent_result(data={}),  # no wave_height key at all
    )
    response = _call(state)
    assert response.data["scenario"] is None
    assert "unavailable" in response.data["explanation"].lower()


def test_failed_weather_or_marine_data_refuses_scenario_assessment() -> None:
    state = _state(
        intent=_intent(is_scenario=True, scenario_variable="wind_speed", scenario_target_value=15.0),
        weather=_agent_result(data={}, status="failed"),
    )
    response = _call(state)
    assert response.data["scenario"] is None


def test_route_endpoint_scenario_discloses_its_own_limited_scope() -> None:
    session = SessionState(last_selected_point={"latitude": OPEN_WATER[0], "longitude": OPEN_WATER[1], "label": "Route A", "source": "route_planning"})
    state = _state(intent=_intent(is_scenario=True, scenario_variable="wind_speed", scenario_target_value=20.0))
    response = _call(state, session=session)
    assert response.data["scenario"]["scope_note"] is not None
    assert "does not re-plan the full route" in response.data["scenario"]["scope_note"]


def test_non_route_scenario_has_no_scope_note() -> None:
    state = _state(intent=_intent(is_scenario=True, scenario_variable="wind_speed", scenario_target_value=20.0))
    response = _call(state)
    assert response.data["scenario"]["scope_note"] is None


def test_deterministic_repeatability() -> None:
    state = _state(intent=_intent(is_scenario=True, scenario_variable="wave_height", scenario_target_value=2.0))
    results = {_call(state).data["scenario"]["risk_score_delta"] for _ in range(5)}
    assert len(results) == 1
