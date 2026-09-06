"""Deterministic hazard detection — Phase 4."""
from __future__ import annotations

from datetime import datetime, timezone

from app.hazard.cyclone import Hazard, relevant_cyclones
from app.hazard.engine import detect_weather_hazards
from app.hazard.safety_status import classify_safety_status
from app.models.contracts import AgentResult
from app.decision.models import Decision
from app.policy.models import SafetyGuardResult

NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)


def _agent_result(*, data: dict, lat: float = 12.8, lon: float = 74.2) -> AgentResult:
    return AgentResult(
        status="ok", data=data, evidence=[], confidence=0.9, source_tier="live", timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo", temporal_validity_status="VALID",
    )


def test_high_wave_above_saturation_is_danger_severity() -> None:
    weather = _agent_result(data={"wind_speed_10m": 3.0, "weathercode": 1})
    marine = _agent_result(data={"wave_height": 3.5})  # above WAVE_SATURATION_M=3.0
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    wave_hazards = [h for h in hazards if h.hazard_type == "HIGH_WAVES"]
    assert len(wave_hazards) == 1
    assert wave_hazards[0].severity == "DANGER"
    assert wave_hazards[0].is_authoritative is False


def test_moderate_wave_below_saturation_is_advisory_not_danger() -> None:
    weather = _agent_result(data={"wind_speed_10m": 3.0, "weathercode": 1})
    marine = _agent_result(data={"wave_height": 2.2})  # 73% of 3.0 -> ADVISORY band
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    wave_hazards = [h for h in hazards if h.hazard_type == "HIGH_WAVES"]
    assert len(wave_hazards) == 1
    assert wave_hazards[0].severity == "ADVISORY"


def test_calm_conditions_produce_no_wave_or_wind_hazard() -> None:
    weather = _agent_result(data={"wind_speed_10m": 3.0, "weathercode": 1})
    marine = _agent_result(data={"wave_height": 0.5})
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    assert hazards == []


def test_high_wind_above_saturation_is_danger_severity() -> None:
    weather = _agent_result(data={"wind_speed_10m": 22.0, "weathercode": 1})  # above WIND_SATURATION_MS=20.0
    marine = _agent_result(data={"wave_height": 0.5})
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    wind_hazards = [h for h in hazards if h.hazard_type == "HIGH_WIND"]
    assert len(wind_hazards) == 1
    assert wind_hazards[0].severity == "DANGER"


def test_thunderstorm_weathercode_produces_explicitly_labeled_proxy_hazard() -> None:
    weather = _agent_result(data={"wind_speed_10m": 3.0, "weathercode": 96})  # WMO thunderstorm-with-hail code
    marine = _agent_result(data={"wave_height": 0.5})
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    proxies = [h for h in hazards if h.hazard_type == "THUNDERSTORM_PROXY"]
    assert len(proxies) == 1
    assert proxies[0].is_proxy is True
    assert proxies[0].is_authoritative is False


def test_deterministic_repeatability() -> None:
    weather = _agent_result(data={"wind_speed_10m": 22.0, "weathercode": 96})
    marine = _agent_result(data={"wave_height": 3.5})
    a = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    b = detect_weather_hazards(weather=weather, marine=marine, latitude=12.8, longitude=74.2)
    assert [h.model_dump(mode="json") for h in a] == [h.model_dump(mode="json") for h in b]


def test_relevant_cyclones_filters_by_distance() -> None:
    near = Hazard(hazard_type="CYCLONE", severity="CRITICAL", title="Near", description="", latitude=13.0, longitude=74.5, source="GDACS", is_authoritative=True)
    far = Hazard(hazard_type="CYCLONE", severity="CRITICAL", title="Far", description="", latitude=-10.0, longitude=150.0, source="GDACS", is_authoritative=True)
    result = relevant_cyclones([near, far], latitude=12.8, longitude=74.2)
    assert len(result) == 1
    assert result[0].title == "Near"
    assert result[0].distance_km is not None and result[0].distance_km < 100


def test_safety_status_danger_when_critical_hazard_active_even_with_recommend_decision() -> None:
    """Safety must never report a favorable status just because the
    Decision Engine's own risk-only view happened to pass — a real active
    hazard overrides it (task's own "hazard-aware fishing/safety" requirement).
    """
    decision = Decision(outcome="RECOMMEND", risk_level="LOW", risk_score=0.1, confidence=1.0, safety_guard_outcome="PASS", reason="risk is LOW")
    safety = SafetyGuardResult(outcome="PASS", reason="no blocking condition triggered", triggered_rule="none")
    critical_hazard = Hazard(hazard_type="CYCLONE", severity="CRITICAL", title="Cyclone", description="", source="GDACS", is_authoritative=True)
    level, _reason = classify_safety_status(decision=decision, safety=safety, hazards=[critical_hazard], unavailable_sources=[])
    assert level == "DANGER"


def test_safety_status_is_unknown_not_safe_when_cyclone_source_unavailable() -> None:
    from app.hazard.models import HazardSourceStatus

    decision = Decision(outcome="RECOMMEND", risk_level="LOW", risk_score=0.1, confidence=1.0, safety_guard_outcome="PASS", reason="risk is LOW")
    safety = SafetyGuardResult(outcome="PASS", reason="no blocking condition triggered", triggered_rule="none")
    unavailable = [HazardSourceStatus(hazard_type="CYCLONE", source="GDACS", is_authoritative=True, programmatically_accessible=True, status="UNAVAILABLE", reason="network failure")]
    level, reason = classify_safety_status(decision=decision, safety=safety, hazards=[], unavailable_sources=unavailable)
    assert level == "UNKNOWN"
    assert "not confirmed safe" in reason


def test_safety_status_is_unknown_when_decision_missing() -> None:
    level, _reason = classify_safety_status(decision=None, safety=None, hazards=[], unavailable_sources=[])
    assert level == "UNKNOWN"
