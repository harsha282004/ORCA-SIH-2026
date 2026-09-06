"""Fishing Intelligence Engine — Phase 3. Verifies `app.fishing.engine`
composes the EXISTING Risk/Suitability/Safety/Decision engines correctly,
with deterministic, reproducible output and safety precedence enforced.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.environmental_sampling import SampleSite
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.fishing.engine import compare_candidates, evaluate_candidate, find_nearest_suitable, rank_candidates
from app.gis.geofence import Geofence, GeofenceCategory
from app.models.contracts import AgentResult
from app.risk.config import get_risk_config

NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)

# Matches tests/routing/test_api_route.py's own open-water/land-fixture points.
OPEN_WATER = (12.80, 74.20)
INSIDE_LAND_FIXTURE = (13.00, 74.90)

LAND_FIXTURE = Geofence(
    id="test-land",
    name="Test land fixture",
    category=GeofenceCategory.LAND,
    geometry={"type": "Polygon", "coordinates": [[[74.80, 12.70], [75.05, 12.70], [75.05, 13.45], [74.80, 13.45], [74.80, 12.70]]]},
    is_authoritative=False,
    source="fixture",
)


def _agent_result(*, data: dict, confidence: float = 0.9, status: str = "ok", lat: float, lon: float) -> AgentResult:
    return AgentResult(
        status=status, data=data, evidence=[], confidence=confidence, source_tier="live", timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo", temporal_validity_status="VALID",
    )


def _calm_site(lat: float, lon: float) -> SampleSite:
    return SampleSite(
        latitude=lat, longitude=lon,
        weather=_agent_result(data={"wind_speed_10m": 3.0, "weathercode": 1}, lat=lat, lon=lon),
        marine=_agent_result(data={"wave_height": 0.5, "sea_surface_temperature": 28.5}, lat=lat, lon=lon),
    )


def _rough_site(lat: float, lon: float) -> SampleSite:
    return SampleSite(
        latitude=lat, longitude=lon,
        weather=_agent_result(data={"wind_speed_10m": 18.0, "weathercode": 96}, lat=lat, lon=lon),
        marine=_agent_result(data={"wave_height": 2.9, "sea_surface_temperature": 27.0}, lat=lat, lon=lon),
    )


def _agent() -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent(gis_agent=GISGeofencingAgent())


def test_calm_but_cyclone_nearby_is_avoided_despite_high_suitability() -> None:
    """Phase 4 task §18's own worked example: "Fishing suitability: HIGH.
    But: Marine hazard: HIGH WIND [or cyclone]. Safety decision: DO NOT
    RECOMMEND." A calm-weather site would normally rank HIGH — passing a
    real, nearby CRITICAL cyclone hazard must override that via the SAME
    Safety Guard/Decision precedence (BLOCK_HAZARD), never a second,
    competing suitability penalty.
    """
    from app.hazard.models import Hazard

    lat, lon = OPEN_WATER
    site = _calm_site(lat, lon)
    without_hazard = evaluate_candidate(
        site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(),
        risk_config=get_risk_config(), at_time=NOW,
    )
    assert without_hazard.status == "ranked"  # calm weather alone is genuinely fine

    nearby_cyclone = Hazard(
        hazard_type="CYCLONE", severity="CRITICAL", title="Test Cyclone", description="", latitude=lat + 0.2, longitude=lon + 0.2,
        source="GDACS (test fixture)", is_authoritative=True,
    )
    with_hazard = evaluate_candidate(
        site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(),
        risk_config=get_risk_config(), at_time=NOW, cyclone_hazards=[nearby_cyclone],
    )
    assert with_hazard.status == "avoid"
    assert with_hazard.decision_outcome == "NO_SAFE_RECOMMENDATION"
    assert with_hazard.safety_outcome == "BLOCK_HAZARD"
    assert with_hazard.active_hazards_checked is True
    assert any(h["hazard_type"] == "CYCLONE" for h in with_hazard.active_hazards)


def test_evaluate_candidate_is_deterministic_and_reproducible() -> None:
    site = _calm_site(*OPEN_WATER)
    a = evaluate_candidate(site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    b = evaluate_candidate(site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    assert a.suitability_score == b.suitability_score
    assert a.risk_score == b.risk_score
    assert a.decision_outcome == b.decision_outcome


def test_calm_open_water_is_ranked_not_avoided() -> None:
    site = _calm_site(*OPEN_WATER)
    candidate = evaluate_candidate(site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    assert candidate.status == "ranked"
    assert candidate.decision_outcome in ("RECOMMEND", "RECOMMEND_WITH_CAUTION")
    assert candidate.safety_outcome == "PASS"


def test_point_inside_hard_geofence_is_avoided_regardless_of_suitability() -> None:
    """The core safety-precedence requirement: a candidate blocked by the
    Safety Guard must NEVER be ranked, even if its raw suitability number
    would otherwise be high.
    """
    site = _calm_site(*INSIDE_LAND_FIXTURE)
    candidate = evaluate_candidate(site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    assert candidate.status == "avoid"
    assert candidate.safety_outcome == "BLOCK_BOUNDARY"
    assert candidate.decision_outcome == "NO_SAFE_RECOMMENDATION"
    # The raw suitability score is still computed and exposed (transparency) —
    # it is the RANKING that excludes it, not the number itself being hidden.
    assert candidate.suitability_score is not None


def test_rough_weather_is_higher_risk_than_calm_weather() -> None:
    calm = evaluate_candidate(site=_calm_site(*OPEN_WATER), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    rough = evaluate_candidate(site=_rough_site(*OPEN_WATER), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    assert rough.risk_score > calm.risk_score
    assert rough.suitability_score < calm.suitability_score


def test_insufficient_data_status_when_weather_failed() -> None:
    lat, lon = OPEN_WATER
    site = SampleSite(latitude=lat, longitude=lon, weather=_agent_result(data={}, status="failed", lat=lat, lon=lon), marine=_calm_site(lat, lon).marine)
    candidate = evaluate_candidate(site=site, geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    assert candidate.status == "insufficient_data"
    assert candidate.suitability_score is None


def test_rank_candidates_orders_by_suitability_and_excludes_avoid_status() -> None:
    calm = evaluate_candidate(site=_calm_site(*OPEN_WATER), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    blocked = evaluate_candidate(site=_calm_site(*INSIDE_LAND_FIXTURE), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)

    ranked, avoid = rank_candidates([calm, blocked])
    assert len(ranked) == 1
    assert ranked[0].rank == 1
    assert blocked in avoid


def test_rank_candidates_respects_min_suitability_and_max_risk_filters() -> None:
    calm = evaluate_candidate(site=_calm_site(*OPEN_WATER), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    ranked, avoid = rank_candidates([calm], min_suitability=0.999)
    assert ranked == []
    assert len(avoid) == 1
    assert "minimum" in avoid[0].reason


def test_find_nearest_suitable_picks_closest_among_ranked_not_all() -> None:
    near = evaluate_candidate(site=_calm_site(12.80, 74.20), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    far = evaluate_candidate(site=_calm_site(13.40, 73.55), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    ranked, _avoid = rank_candidates([far, near])
    nearest = find_nearest_suitable(ranked, origin_latitude=12.80, origin_longitude=74.20, gis_agent=GISGeofencingAgent())
    assert nearest is not None
    assert nearest.latitude == near.latitude
    assert nearest.distance_km is not None and nearest.distance_km < 1.0


def test_find_nearest_suitable_returns_none_when_nothing_ranked() -> None:
    assert find_nearest_suitable([], origin_latitude=12.8, origin_longitude=74.2, gis_agent=GISGeofencingAgent()) is None


def test_compare_candidates_prefers_higher_suitability_among_eligible() -> None:
    calm = evaluate_candidate(site=_calm_site(*OPEN_WATER), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    rough = evaluate_candidate(site=_rough_site(13.40, 73.55), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    comparison = compare_candidates([calm, rough])
    assert comparison.better_candidate_index == 0  # calm (higher suitability) beats rough


def test_compare_candidates_returns_no_preference_when_all_blocked() -> None:
    blocked = evaluate_candidate(site=_calm_site(*INSIDE_LAND_FIXTURE), geofences=[LAND_FIXTURE], gis_agent=GISGeofencingAgent(), risk_suitability_agent=_agent(), risk_config=get_risk_config(), at_time=NOW)
    comparison = compare_candidates([blocked, blocked])
    assert comparison.better_candidate_index is None
    assert "no preference" in comparison.reason
