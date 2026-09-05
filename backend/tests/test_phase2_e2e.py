"""Phase 2 end-to-end deterministic chain test:

    NORMALIZED OBSERVATIONS (Phase 1 contract, reused not re-invented)
        -> GIS VALIDATION
        -> GEOFENCE CHECK
        -> RISK COMPONENTS
        -> RISK SCORE / LEVEL
        -> CONFIDENCE
        -> SAFETY GUARD
        -> DECISION ENGINE
        -> STRUCTURED DECISION

No LLM anywhere in this chain. All inputs are controlled fixtures — this
test must never be mistaken for a live-data test (see
backend/tests/test_live_open_meteo.py and test_pipeline_e2e.py in the
Phase 1 suite for that).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.decision.engine import make_decision
from app.fabric.spatial import validate_point
from app.gis.geofence import Geofence, GeofenceCategory, evaluate_point_against_geofences
from app.models.contracts import NormalizedObservation, QualityMetadata
from app.reasoning.confidence import ConfidenceInputs, compute_confidence
from app.risk.components import (
    advisory_or_hazard_risk,
    coast_distance_risk,
    data_confidence_penalty_risk,
    restricted_zone_distance_risk,
    wave_risk,
    wind_risk,
)
from app.risk.config import get_risk_config
from app.risk.hazard_proxies import lightning_thunderstorm_proxy
from app.risk.engine import NormalizedRiskComponents, compute_risk
from app.policy.models import SafetyFacts
from app.policy.safety_guard import evaluate_safety_guard

CONFIG = get_risk_config()
NOW = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)

LAND_FIXTURE = Geofence(
    id="land-fixture-1",
    name="Fixture coastline",
    category=GeofenceCategory.LAND,
    geometry={
        "type": "Polygon",
        "coordinates": [[[74.80, 12.80], [74.90, 12.80], [74.90, 12.90], [74.80, 12.90], [74.80, 12.80]]],
    },
    is_authoritative=True,
    source="fixture",
)


def make_fixture_observation(parameter: str, value: float, *, lat: float, lon: float) -> NormalizedObservation:
    """A controlled TEST FIXTURE — not live environmental data. Reuses the
    exact Phase 1 NormalizedObservation contract (app.models.contracts) so
    Phase 2's deterministic core is proven against the same shape real
    Open-Meteo data already produces (see backend/tests/data/*.py).
    """
    return NormalizedObservation(
        source="fixture",
        source_type="forecast",
        source_tier="synthetic",
        parameter=parameter,
        value=value,
        unit="fixture_unit",
        latitude=lat,
        longitude=lon,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=NOW + timedelta(hours=1),
        is_forecast=True,
        retrieved_at=NOW,
        mode="demo",
        is_live=False,
        quality=QualityMetadata(),
    )


def run_full_chain(
    *,
    latitude: float,
    longitude: float,
    wave_height_m: float,
    wind_speed_ms: float,
    weathercode: float,
    geofences: list[Geofence],
    restricted_zone_distance_km: float,
    coast_distance_km: float,
) -> dict:
    # 1. GIS VALIDATION
    validate_point(latitude, longitude)

    # 2. GEOFENCE CHECK
    geofence_result = evaluate_point_against_geofences(latitude, longitude, geofences, at_time=NOW)

    # 3. RISK COMPONENTS (derived from fixture NormalizedObservations)
    wave_obs = make_fixture_observation("wave_height", wave_height_m, lat=latitude, lon=longitude)
    wind_obs = make_fixture_observation("wind_speed_10m", wind_speed_ms, lat=latitude, lon=longitude)
    weathercode_obs = make_fixture_observation("weathercode", weathercode, lat=latitude, lon=longitude)

    components = NormalizedRiskComponents(
        wave=wave_risk(wave_obs.value),
        wind=wind_risk(wind_obs.value),
        advisory_or_hazard_flag=advisory_or_hazard_risk("none"),
        lightning_thunderstorm_proxy=lightning_thunderstorm_proxy(weathercode_obs.value),
        restricted_zone_distance=restricted_zone_distance_risk(restricted_zone_distance_km),
        coast_distance=coast_distance_risk(coast_distance_km),
        data_confidence_penalty=data_confidence_penalty_risk(0.9),  # placeholder, overwritten below once confidence is known
    )

    # 4. CONFIDENCE (independent of risk_score itself)
    confidence_inputs = ConfidenceInputs(freshness=1.0, completeness=1.0, agreement=1.0)
    confidence = compute_confidence(confidence_inputs, CONFIG.confidence_weights)

    # Recompute the data_confidence_penalty component from the *actual*
    # confidence value, rather than the placeholder above — keeps risk and
    # confidence as genuinely separate calculations while still letting the
    # risk score reflect real confidence, per architecture.md §22.
    components = components.model_copy(update={"data_confidence_penalty": data_confidence_penalty_risk(confidence)})

    # 5. RISK SCORE / LEVEL
    risk_result = compute_risk(components, CONFIG.risk_weights, CONFIG.risk_thresholds)

    # 6. SAFETY GUARD
    safety_facts = SafetyFacts(
        has_boundary_violation=geofence_result.blocked,
        has_critical_missing_data=False,
        confidence=confidence,
        has_active_high_severity_advisory=False,
    )
    safety_result = evaluate_safety_guard(safety_facts, min_confidence_threshold=CONFIG.safety.min_confidence_threshold)

    # 7. DECISION ENGINE
    decision = make_decision(
        risk_level=risk_result.level,
        risk_score=risk_result.score,
        confidence=confidence,
        min_confidence_threshold=CONFIG.safety.min_confidence_threshold,
        safety_guard_result=safety_result,
        alternative_exists=False,
    )

    return {
        "geofence_result": geofence_result,
        "risk_result": risk_result,
        "confidence": confidence,
        "safety_result": safety_result,
        "decision": decision,
    }


def test_full_chain_calm_open_water_recommends() -> None:
    outcome = run_full_chain(
        latitude=13.075,
        longitude=74.275,
        wave_height_m=0.5,
        wind_speed_ms=3.0,
        weathercode=1,  # not a thunderstorm code
        geofences=[LAND_FIXTURE],
        restricted_zone_distance_km=20.0,
        coast_distance_km=8.0,
    )

    assert outcome["geofence_result"].allowed is True
    assert outcome["risk_result"].level == "LOW"
    assert outcome["safety_result"].outcome == "PASS"
    assert outcome["decision"].outcome == "RECOMMEND"


def test_full_chain_point_inside_land_geofence_blocks() -> None:
    outcome = run_full_chain(
        latitude=12.85,
        longitude=74.85,  # inside LAND_FIXTURE
        wave_height_m=0.5,
        wind_speed_ms=3.0,
        weathercode=1,
        geofences=[LAND_FIXTURE],
        restricted_zone_distance_km=20.0,
        coast_distance_km=8.0,
    )

    assert outcome["geofence_result"].blocked is True
    assert outcome["safety_result"].outcome == "BLOCK_BOUNDARY"
    assert outcome["decision"].outcome == "NO_SAFE_RECOMMENDATION"
    assert outcome["decision"].safety_guard_outcome == "BLOCK_BOUNDARY"


def test_full_chain_severe_weather_produces_high_risk() -> None:
    outcome = run_full_chain(
        latitude=13.075,
        longitude=74.275,
        wave_height_m=3.5,  # above saturation
        wind_speed_ms=22.0,  # above saturation
        weathercode=99,  # thunderstorm proxy
        geofences=[LAND_FIXTURE],
        restricted_zone_distance_km=1.0,
        coast_distance_km=75.0,
        )

    assert outcome["risk_result"].level == "HIGH"
    assert outcome["decision"].outcome == "NO_SAFE_RECOMMENDATION"  # HIGH risk, no alternative supplied


def test_full_chain_missing_critical_data_blocks() -> None:
    # No GIS/risk computation possible without a wave reading in a real
    # pipeline — this test exercises the Safety Guard's missing-data path
    # directly, since Phase 2's Risk Engine itself refuses (by design,
    # see MissingRiskComponentError) to silently score missing data as zero.
    safety_facts = SafetyFacts(
        has_boundary_violation=False,
        has_critical_missing_data=True,
        confidence=0.9,
        has_active_high_severity_advisory=False,
    )
    safety_result = evaluate_safety_guard(safety_facts, min_confidence_threshold=CONFIG.safety.min_confidence_threshold)
    decision = make_decision(
        risk_level="LOW",
        risk_score=0.1,
        confidence=0.9,
        min_confidence_threshold=CONFIG.safety.min_confidence_threshold,
        safety_guard_result=safety_result,
    )

    assert safety_result.outcome == "BLOCK_MISSING_DATA"
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_full_chain_is_deterministic() -> None:
    kwargs = dict(
        latitude=13.075,
        longitude=74.275,
        wave_height_m=1.2,
        wind_speed_ms=8.0,
        weathercode=3,
        geofences=[LAND_FIXTURE],
        restricted_zone_distance_km=15.0,
        coast_distance_km=10.0,
    )
    outcomes = {run_full_chain(**kwargs)["decision"].outcome for _ in range(5)}
    scores = {run_full_chain(**kwargs)["risk_result"].score for _ in range(5)}
    assert len(outcomes) == 1
    assert len(scores) == 1
