"""Alert Engine — architecture.md §29. Pure unit tests: no Redis, no
network, no agents — every hazard-detection/state-diff function here is a
plain deterministic function of its inputs.
"""
from __future__ import annotations

from app.alerts.engine import detect_hazard_severities, diff_alert_states
from app.risk.config import get_risk_config
from tests.orchestration.conftest import make_marine_result, make_weather_result

THRESHOLDS = get_risk_config().risk_thresholds


def test_calm_conditions_detect_no_hazards() -> None:
    weather = make_weather_result(wind_speed_10m=2.0, weathercode=0)
    marine = make_marine_result(wave_height=0.3)
    current = detect_hazard_severities(
        weather=weather, marine=marine, distance_to_hard_geofence_km=50.0, overall_risk_score=0.1, overall_risk_level="LOW"
    )
    assert current == {}


def test_high_waves_are_detected() -> None:
    weather = make_weather_result(wind_speed_10m=2.0, weathercode=0)
    marine = make_marine_result(wave_height=2.5)  # >= 0.5 normalized at WAVE_SATURATION_M=3.0
    current = detect_hazard_severities(
        weather=weather, marine=marine, distance_to_hard_geofence_km=50.0, overall_risk_score=0.4, overall_risk_level="MODERATE"
    )
    assert "wave" in current
    assert "risk_threshold" in current


def test_thunderstorm_weathercode_triggers_lightning_proxy_with_disclosed_terminology() -> None:
    weather = make_weather_result(wind_speed_10m=2.0, weathercode=96)  # WMO thunderstorm code
    marine = make_marine_result(wave_height=0.3)
    current = detect_hazard_severities(
        weather=weather, marine=marine, distance_to_hard_geofence_km=50.0, overall_risk_score=0.1, overall_risk_level="LOW"
    )
    assert "lightning_thunderstorm_proxy" in current
    severity, message = current["lightning_thunderstorm_proxy"]
    assert severity == 1.0
    assert "DAMINI" in message
    assert "not real-time lightning-strike detection" in message


def test_close_to_restricted_zone_is_detected() -> None:
    weather = make_weather_result(wind_speed_10m=2.0, weathercode=0)
    marine = make_marine_result(wave_height=0.3)
    current = detect_hazard_severities(
        weather=weather, marine=marine, distance_to_hard_geofence_km=1.0, overall_risk_score=0.1, overall_risk_level="LOW"
    )
    assert "restricted_zone_distance" in current


def test_first_detection_of_a_hazard_is_state_new() -> None:
    current = {"wave": (0.6, "wave msg")}
    alerts, next_state = diff_alert_states(previous={}, current=current, thresholds=THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].state == "New"
    assert next_state == {"wave": 0.6}


def test_unchanged_hazard_is_not_repeated() -> None:
    current = {"wave": (0.6, "wave msg")}
    alerts, _next_state = diff_alert_states(previous={"wave": 0.6}, current=current, thresholds=THRESHOLDS)
    assert alerts == []


def test_hazard_crossing_into_a_higher_risk_band_is_escalated() -> None:
    # LOW->HIGH band crossing at the same-ish thresholds config.
    current = {"wave": (0.9, "wave msg")}
    alerts, _next_state = diff_alert_states(previous={"wave": 0.1}, current=current, thresholds=THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].state == "Escalated"


def test_hazard_changing_within_the_same_band_is_updated_not_escalated() -> None:
    current = {"wave": (0.62, "wave msg")}
    alerts, _next_state = diff_alert_states(previous={"wave": 0.55}, current=current, thresholds=THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].state == "Updated"


def test_hazard_no_longer_present_is_resolved_and_dropped_from_next_state() -> None:
    alerts, next_state = diff_alert_states(previous={"wave": 0.6}, current={}, thresholds=THRESHOLDS)
    assert len(alerts) == 1
    assert alerts[0].state == "Resolved"
    assert next_state == {}


def test_a_resolved_hazard_is_reported_exactly_once() -> None:
    # Second call after resolution: the hazard is already gone from
    # persisted state, so it must not appear again.
    _first_alerts, state_after_resolution = diff_alert_states(previous={"wave": 0.6}, current={}, thresholds=THRESHOLDS)
    second_alerts, _next_state = diff_alert_states(previous=state_after_resolution, current={}, thresholds=THRESHOLDS)
    assert second_alerts == []
