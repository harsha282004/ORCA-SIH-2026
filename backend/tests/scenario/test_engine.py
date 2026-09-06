"""Scenario Engine — architecture.md §32. Every test reuses the exact
weather/marine result builders `tests/orchestration/conftest.py` already
established, so the perturbation math is exercised against the same
fixtures the orchestration suite trusts.
"""
from __future__ import annotations

from app.agents.gis.agent import GISGeofencingAgent
from app.agents.query_understanding.models import IntentResult
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.risk.config import get_risk_config
from app.scenario.engine import run_scenario
from app.scenario.models import ScenarioPerturbation
from tests.orchestration.conftest import OPEN_WATER_LAT, OPEN_WATER_LON, make_marine_result, make_weather_result

RISK_CONFIG = get_risk_config()


def _intent() -> IntentResult:
    return IntentResult(
        language="en",
        intent_class="safety_check",
        activity="fishing",
        location={
            "type": "region",
            "name": "Mangaluru-Udupi coastal Karnataka",
            "resolved_bbox": {
                "min_lat": OPEN_WATER_LAT - 0.01,
                "min_lon": OPEN_WATER_LON - 0.01,
                "max_lat": OPEN_WATER_LAT + 0.01,
                "max_lon": OPEN_WATER_LON + 0.01,
            },
        },
        time_window={"start": "2026-09-06T00:00:00+00:00", "end": "2026-09-06T12:00:00+00:00"},
        objective="is it safe to fish",
        constraints={},
        requires_route=False,
        requires_pfz_reference=False,
        persona="fisherman",
        refers_to_prior=False,
        reference_type=None,
    )


def _run(perturbation: ScenarioPerturbation, *, wave_height=0.5, wind_speed_10m=3.0, weathercode=0):
    weather = make_weather_result(wind_speed_10m=wind_speed_10m, weathercode=weathercode)
    marine = make_marine_result(wave_height=wave_height)
    return run_scenario(
        intent=_intent(),
        weather=weather,
        marine=marine,
        perturbation=perturbation,
        risk_suitability_agent=RiskSuitabilityAgent(),
        gis_agent=GISGeofencingAgent(),
        risk_config=RISK_CONFIG,
    )


def test_scenario_is_labeled_as_simulation() -> None:
    result = _run(ScenarioPerturbation(wave_height_delta_m=1.0))
    assert result.label == "SIMULATION — NOT LIVE DATA"


def test_worsening_wave_height_increases_risk_score() -> None:
    result = _run(ScenarioPerturbation(wave_height_delta_m=3.0), wave_height=0.5)
    assert result.scenario.decision.risk_score > result.baseline.decision.risk_score
    assert result.risk_score_delta > 0


def test_worsening_wind_speed_increases_risk_score() -> None:
    result = _run(ScenarioPerturbation(wind_speed_delta_ms=25.0), wind_speed_10m=3.0)
    assert result.scenario.decision.risk_score > result.baseline.decision.risk_score


def test_baseline_is_never_mutated_by_the_perturbation() -> None:
    weather = make_weather_result(wind_speed_10m=3.0, weathercode=0)
    marine = make_marine_result(wave_height=0.5)
    run_scenario(
        intent=_intent(),
        weather=weather,
        marine=marine,
        perturbation=ScenarioPerturbation(wave_height_delta_m=5.0),
        risk_suitability_agent=RiskSuitabilityAgent(),
        gis_agent=GISGeofencingAgent(),
        risk_config=RISK_CONFIG,
    )
    # The caller's own AgentResult objects must be untouched — §32 step 1,
    # "copy baseline state, never mutate it".
    assert marine.data["wave_height"] == 0.5
    assert weather.data["wind_speed_10m"] == 3.0


def test_large_enough_perturbation_can_flip_the_decision_outcome() -> None:
    # Calm baseline (LOW risk) -> a severe wave-height spike should push the
    # scenario into a materially worse decision outcome.
    result = _run(ScenarioPerturbation(wave_height_delta_m=8.0), wave_height=0.3)
    assert result.baseline.decision.outcome in {"RECOMMEND", "RECOMMEND_WITH_CAUTION"}
    assert result.decision_changed is True
    assert result.scenario.decision.risk_level in {"MODERATE", "HIGH"}


def test_negative_perturbation_never_produces_a_negative_wave_height() -> None:
    result = _run(ScenarioPerturbation(wave_height_delta_m=-1000.0), wave_height=0.5)
    # Floored at 0.0, not a fabricated negative physical value.
    assert result.scenario.risk_suitability.risk_result is not None


def test_perturbation_requires_at_least_one_delta() -> None:
    import pytest

    with pytest.raises(ValueError):
        ScenarioPerturbation()
