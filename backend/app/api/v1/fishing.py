"""Fishing Intelligence endpoints — Phase 3.

New capability, not a duplicate of anything existing: `GET /api/v1/layers/
suitability` (Phase 2) already exposes a raw per-sample suitability GRID
for map rendering; nothing existing does candidate RANKING, nearest-
suitable SEARCH, multi-area COMPARISON, or time-window evaluation. This
router adds exactly those four capabilities, composing `app.fishing.engine`
(itself a composition of the EXISTING deterministic Risk/Suitability/
Safety/Decision engines — see that module's own docstring) — no new
scoring formula anywhere in this file.

    GET  /fishing/candidates  — generate + rank candidates across the demo bbox (DISCOVER / "best available areas")
    GET  /fishing/nearest     — nearest candidate that PASSES safety/risk/suitability filtering, from an origin point
    POST /fishing/compare     — deterministic comparison between 2+ specific points
    GET  /fishing/temporal    — suitability for ONE point across several real hourly timestamps

None of these call an LLM. None of them let the caller override a
deterministic result.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.agents.environmental_sampling import SampleSite
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import get_settings
from app.fishing.engine import compare_candidates, evaluate_candidate, find_nearest_suitable, generate_candidates
from app.fishing.models import FishingCandidate
from app.fishing.temporal import evaluate_temporal_suitability, select_best_time_by_suitability
from app.risk.config import get_risk_config
from app.suitability.config import get_suitability_weights

router = APIRouter()


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_weather_agent() -> WeatherIntelligenceAgent:
    return WeatherIntelligenceAgent()


def get_oceanographic_agent() -> OceanographicIntelligenceAgent:
    return OceanographicIntelligenceAgent()


def get_risk_suitability_agent(gis_agent: GISGeofencingAgent = Depends(get_gis_agent)) -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent(gis_agent=gis_agent, risk_config=get_risk_config(), suitability_weights=get_suitability_weights())


def get_hazard_cache():
    """Phase 4: the same Redis-backed `AgentCache` `app.api.v1.safety` uses
    for the cyclone check (best-effort — a cache/Redis miss degrades to a
    live GDACS fetch, never a crash), so fishing candidate generation gets
    real hazard-awareness (task §18) without polling GDACS once per
    candidate — see `app.fishing.engine.generate_candidates`'s own docstring.
    """
    from app.agents.common.cache import AgentCache
    from app.services.cache import get_client as get_redis_client

    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001
        client = None
    return AgentCache(client, ttl_seconds=1800)


def _candidate_feature(c: FishingCandidate) -> dict:
    return {
        "type": "Feature",
        "properties": c.model_dump(mode="json", exclude={"latitude", "longitude"}),
        "geometry": {"type": "Point", "coordinates": [c.longitude, c.latitude]},
    }


# --- GET /fishing/candidates ------------------------------------------------


@router.get("/fishing/candidates")
def get_fishing_candidates(
    at: datetime | None = Query(default=None),
    min_suitability: float = Query(default=0.0, ge=0.0, le=1.0),
    max_risk: float = Query(default=1.0, ge=0.0, le=1.0),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    hazard_cache=Depends(get_hazard_cache),
) -> dict:
    settings = get_settings()
    risk_config = get_risk_config()

    result = generate_candidates(
        bbox=settings.demo_bbox,
        requested_time=at,
        weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent,
        gis_agent=gis_agent,
        risk_suitability_agent=suitability_agent,
        risk_config=risk_config,
        hazard_cache=hazard_cache,
    )
    if min_suitability > 0.0 or max_risk < 1.0:
        from app.fishing.engine import rank_candidates

        result.ranked, extra_avoid = rank_candidates(result.ranked, min_suitability=min_suitability, max_risk_score=max_risk)
        result.avoid = result.avoid + extra_avoid
        result.ranked_count = len(result.ranked)
        result.avoid_count = len(result.avoid)

    features = [_candidate_feature(c) for c in result.ranked] + [_candidate_feature(c) for c in result.avoid]

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "layer": "fishing-candidates",
            "classification": "derived",
            "method": result.method,
            "sample_count": result.sample_count,
            "ranked_count": result.ranked_count,
            "avoid_count": result.avoid_count,
            "requested_time": result.requested_time.isoformat(),
            "generated_at": result.generated_at.isoformat(),
            "source": "ORCA deterministic Risk & Suitability Agent, Safety Guard, Decision Engine (app.fishing.engine)",
            "pfz_status": "unavailable — see GET /api/v1/layers/chlorophyll and docs/PHASE_1_MARINE_DATA_FOUNDATION_REPORT.md",
        },
        "errors": None,
    }


# --- GET /fishing/nearest ---------------------------------------------------


@router.get("/fishing/nearest")
def get_nearest_suitable(
    latitude: float = Query(...),
    longitude: float = Query(...),
    at: datetime | None = Query(default=None),
    min_suitability: float = Query(default=0.0, ge=0.0, le=1.0),
    max_risk: float = Query(default=1.0, ge=0.0, le=1.0),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    hazard_cache=Depends(get_hazard_cache),
) -> dict:
    settings = get_settings()
    if not settings.demo_bbox.contains(latitude, longitude):
        return {"data": None, "meta": None, "errors": [{"code": "OUT_OF_DOMAIN", "message": "origin is outside the configured ORCA demo bbox"}]}

    risk_config = get_risk_config()
    result = generate_candidates(
        bbox=settings.demo_bbox, requested_time=at, weather_agent=weather_agent, oceanographic_agent=oceanographic_agent,
        gis_agent=gis_agent, risk_suitability_agent=suitability_agent, risk_config=risk_config, hazard_cache=hazard_cache,
    )
    from app.fishing.engine import rank_candidates

    ranked, _avoid = rank_candidates(result.ranked, min_suitability=min_suitability, max_risk_score=max_risk)
    nearest = find_nearest_suitable(ranked, origin_latitude=latitude, origin_longitude=longitude, gis_agent=gis_agent)

    if nearest is None:
        return {
            "data": None,
            "meta": {
                "reason": "no candidate in the sampled grid satisfies the requested safety/risk/suitability constraints",
                "sample_count": result.sample_count,
                "requested_time": result.requested_time.isoformat(),
            },
            "errors": None,
        }

    return {
        "data": _candidate_feature(nearest),
        "meta": {
            "origin": {"latitude": latitude, "longitude": longitude},
            "method": "nearest candidate among those that passed deterministic safety/risk/suitability filtering — never nearest by distance alone",
            "sample_count": result.sample_count,
            "requested_time": result.requested_time.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "errors": None,
    }


# --- POST /fishing/compare --------------------------------------------------


class ComparePoint(BaseModel):
    latitude: float
    longitude: float


class CompareRequest(BaseModel):
    points: list[ComparePoint]
    at: datetime | None = None


@router.post("/fishing/compare")
def compare_areas(
    request: CompareRequest,
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    hazard_cache=Depends(get_hazard_cache),
) -> dict:
    settings = get_settings()
    if not (2 <= len(request.points) <= 5):
        return {"data": None, "meta": None, "errors": [{"code": "INVALID_REQUEST", "message": "compare requires between 2 and 5 points"}]}
    for p in request.points:
        if not settings.demo_bbox.contains(p.latitude, p.longitude):
            return {"data": None, "meta": None, "errors": [{"code": "OUT_OF_DOMAIN", "message": f"point ({p.latitude}, {p.longitude}) is outside the configured ORCA demo bbox"}]}

    at_time = request.at or datetime.now(timezone.utc)
    risk_config = get_risk_config()
    geofences, _metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)
    from app.hazard.cyclone import fetch_active_cyclone_hazards

    cyclone_hazards, _tier = fetch_active_cyclone_hazards(cache=hazard_cache)  # one fetch for the whole comparison, not per-point

    def fetch_and_evaluate(point: ComparePoint) -> FishingCandidate:
        weather = weather_agent.get_weather(latitude=point.latitude, longitude=point.longitude, requested_time=at_time)
        marine = oceanographic_agent.get_marine(latitude=point.latitude, longitude=point.longitude, requested_time=at_time)
        site = SampleSite(latitude=point.latitude, longitude=point.longitude, weather=weather, marine=marine)
        return evaluate_candidate(
            site=site, geofences=geofences, gis_agent=gis_agent, risk_suitability_agent=suitability_agent,
            risk_config=risk_config, at_time=at_time, cyclone_hazards=cyclone_hazards,
        )

    with ThreadPoolExecutor(max_workers=len(request.points)) as executor:
        candidates = list(executor.map(fetch_and_evaluate, request.points))

    comparison = compare_candidates(candidates)

    return {
        "data": {
            "candidates": [c.model_dump(mode="json") for c in comparison.candidates],
            "better_candidate_index": comparison.better_candidate_index,
            "reason": comparison.reason,
        },
        "meta": {"requested_time": at_time.isoformat(), "generated_at": comparison.generated_at.isoformat(), "source": "ORCA deterministic Risk & Suitability Agent (app.fishing.engine.compare_candidates)"},
        "errors": None,
    }


# --- GET /fishing/temporal ---------------------------------------------------


@router.get("/fishing/temporal")
def get_temporal_suitability(
    latitude: float = Query(...),
    longitude: float = Query(...),
    hours: int = Query(default=6, ge=1, le=24),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
) -> dict:
    """Suitability for ONE point across several REAL Open-Meteo hourly
    steps. Reuses `app.fishing.temporal.evaluate_temporal_suitability`,
    which fetches the real 24-hour series ONCE (via the same
    `parse_hourly_timeseries` `GET /api/v1/layers/marine-timeseries`
    already uses) and computes risk/suitability per real hour from the
    existing deterministic component functions — see that module's own
    docstring for exactly why this path exists separately from
    `app.fishing.engine.evaluate_candidate`. Bathymetry/chlorophyll/INCOIS
    SST are NOT evaluated per-hour here — they have no hourly temporal
    dimension (Phase 1) and are correctly excluded, not fabricated.
    """
    settings = get_settings()
    if not settings.demo_bbox.contains(latitude, longitude):
        return {"data": None, "meta": None, "errors": [{"code": "OUT_OF_DOMAIN", "message": "point is outside the configured ORCA demo bbox"}]}

    risk_config = get_risk_config()
    suitability_weights = get_suitability_weights()

    series = evaluate_temporal_suitability(
        latitude=latitude, longitude=longitude, hours=hours, gis_agent=gis_agent,
        risk_config=risk_config, suitability_weights=suitability_weights,
    )

    best_index = select_best_time_by_suitability(series)

    return {
        "data": {
            "latitude": latitude,
            "longitude": longitude,
            "series": [c.model_dump(mode="json") for c in series],
            "recommended_index": best_index,
        },
        "meta": {
            "hours_evaluated": hours,
            "temporal_resolution": "1 hour (Open-Meteo's native hourly cadence)",
            "is_forecast": True,
            "note": "Wave/wind/SST/currents genuinely vary per hour (real Open-Meteo forecast steps). GEBCO bathymetry is static/reference and INCOIS chlorophyll/SST have no hourly dimension — none are part of this per-hour evaluation.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "errors": None,
    }
