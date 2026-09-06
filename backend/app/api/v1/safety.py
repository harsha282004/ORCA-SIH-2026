"""Marine Safety & Hazard Intelligence endpoints — Phase 4.

New capability, not a duplicate: nothing existing computes a combined
safety STATUS (SAFE/CAUTION/WARNING/DANGER/UNKNOWN) or exposes detected
HAZARDS as first-class objects. This module composes the EXISTING
deterministic pipeline exactly as `app.orchestration.nodes
.OrchestrationNodes` already does for one point (Weather/Oceanographic/GIS
-> Risk & Suitability -> Safety Guard -> Decision), with ONE addition: the
Safety Guard's `has_active_high_severity_advisory` fact — hardcoded False
everywhere else in the codebase (an honest, documented Phase 5 limitation:
"no official advisory ingestion exists yet") — is, for the FIRST time,
wired to a REAL value here: whether `app.hazard.engine.detect_all_hazards`
found an actual DANGER/CRITICAL-severity hazard (a real cyclone within
range, or a saturating wave/wind reading). `derive_safety_facts` itself is
NOT modified (zero regression risk to any existing caller); this module
only overrides the one field it already documents as a placeholder.

    GET /safety/status   — combined marine safety status for a point/time
    GET /safety/hazards  — the real detected hazards for a point/time, plus honestly-unavailable sources
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import get_settings
from app.decision.engine import make_decision, risk_inputs_for_decision
from app.fishing.temporal import evaluate_temporal_suitability, select_best_time_by_risk
from app.hazard.engine import detect_all_hazards
from app.hazard.safety_status import build_marine_safety_status
from app.policy.safety_guard import derive_safety_facts, evaluate_safety_guard
from app.risk.config import get_risk_config
from app.services.cache import get_client as get_redis_client
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
    from app.agents.common.cache import AgentCache

    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001 — best-effort; a cache miss is never fatal
        client = None
    return AgentCache(client, ttl_seconds=1800)


def _evaluate_safety(
    *, latitude: float, longitude: float, at: datetime | None, gis_agent, weather_agent, oceanographic_agent, suitability_agent, hazard_cache,
):
    settings = get_settings()
    risk_config = get_risk_config()
    requested_time = at or datetime.now(timezone.utc)

    weather = weather_agent.get_weather(latitude=latitude, longitude=longitude, requested_time=requested_time)
    marine = oceanographic_agent.get_marine(latitude=latitude, longitude=longitude, requested_time=requested_time)
    geofences, _metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)
    boundary_check = gis_agent.evaluate_point(latitude, longitude, geofences=geofences)

    risk_suitability = suitability_agent.evaluate(
        weather=weather, marine=marine, latitude=latitude, longitude=longitude, distance_to_zone_km=0.0,
    )

    hazards, unavailable_sources = detect_all_hazards(weather=weather, marine=marine, latitude=latitude, longitude=longitude, cache=hazard_cache)
    critical_hazard_active = any(h.severity in ("DANGER", "CRITICAL") for h in hazards)

    # The ONE real wiring of the Safety Guard's previously-always-False
    # advisory fact — see module docstring. derive_safety_facts itself is
    # untouched; only this ONE field on its output is overridden here.
    facts = derive_safety_facts(weather=weather, marine=marine, boundary_check=boundary_check, risk_suitability=risk_suitability)
    facts = facts.model_copy(update={"has_active_high_severity_advisory": critical_hazard_active})
    safety = evaluate_safety_guard(facts, min_confidence_threshold=risk_config.safety.min_confidence_threshold)

    risk_level, risk_score, confidence = risk_inputs_for_decision(risk_suitability)
    decision = make_decision(
        risk_level=risk_level, risk_score=risk_score, confidence=confidence,
        min_confidence_threshold=risk_config.safety.min_confidence_threshold, safety_guard_result=safety, alternative_exists=False,
    )

    status = build_marine_safety_status(
        risk_suitability=risk_suitability, decision=decision, safety=safety, hazards=hazards, unavailable_sources=unavailable_sources,
    )
    return status, weather, marine


@router.get("/safety/status")
def get_safety_status(
    latitude: float = Query(...),
    longitude: float = Query(...),
    at: datetime | None = Query(default=None),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    hazard_cache=Depends(get_hazard_cache),
) -> dict:
    settings = get_settings()
    if not settings.demo_bbox.contains(latitude, longitude):
        return {"data": None, "meta": None, "errors": [{"code": "OUT_OF_DOMAIN", "message": "point is outside the configured ORCA demo bbox"}]}

    status, weather, marine = _evaluate_safety(
        latitude=latitude, longitude=longitude, at=at, gis_agent=gis_agent, weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent, suitability_agent=suitability_agent, hazard_cache=hazard_cache,
    )

    return {
        "data": status.model_dump(mode="json"),
        "meta": {
            "latitude": latitude, "longitude": longitude,
            "weather_source_tier": weather.source_tier, "marine_source_tier": marine.source_tier,
            "requested_time": (at or datetime.now(timezone.utc)).isoformat(),
            "generated_at": status.generated_at.isoformat(),
            "source": "ORCA deterministic Risk/Safety/Decision Engine + app.hazard.engine (Phase 4)",
        },
        "errors": None,
    }


@router.get("/safety/hazards")
def get_hazards(
    latitude: float = Query(...),
    longitude: float = Query(...),
    at: datetime | None = Query(default=None),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    hazard_cache=Depends(get_hazard_cache),
) -> dict:
    settings = get_settings()
    if not settings.demo_bbox.contains(latitude, longitude):
        return {"data": None, "meta": None, "errors": [{"code": "OUT_OF_DOMAIN", "message": "point is outside the configured ORCA demo bbox"}]}

    requested_time = at or datetime.now(timezone.utc)
    weather = weather_agent.get_weather(latitude=latitude, longitude=longitude, requested_time=requested_time)
    marine = oceanographic_agent.get_marine(latitude=latitude, longitude=longitude, requested_time=requested_time)
    hazards, unavailable_sources = detect_all_hazards(weather=weather, marine=marine, latitude=latitude, longitude=longitude, cache=hazard_cache)

    features = [
        {
            "type": "Feature",
            "properties": h.model_dump(mode="json", exclude={"latitude", "longitude"}),
            "geometry": {"type": "Point", "coordinates": [h.longitude, h.latitude]} if h.latitude is not None else None,
        }
        for h in hazards
    ]

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "latitude": latitude, "longitude": longitude,
            "hazard_count": len(hazards),
            "unavailable_sources": [s.model_dump(mode="json") for s in unavailable_sources],
            "requested_time": requested_time.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "app.hazard.engine.detect_all_hazards (Phase 4)",
        },
        "errors": None,
    }


@router.get("/safety/sources")
def get_hazard_source_status() -> dict:
    """The full, honest hazard-source audit (docs/PHASE_4_..._REPORT.md
    §3), served live so the frontend's "Data Availability" panel reads
    real, code-level status rather than a hardcoded UI list that could
    silently drift out of sync with reality.
    """
    from app.hazard.models import HazardSourceStatus

    sources = [
        HazardSourceStatus(
            hazard_type="CYCLONE", source="GDACS (aggregating IMD/RSMC/JTWC bulletins) — https://www.gdacs.org/",
            is_authoritative=True, programmatically_accessible=True, status="AVAILABLE",
            reason="Real, live, no-key-required GeoJSON API, verified this phase. IMD's own direct cyclone_track API "
            "exists but requires an API key this deployment does not have (HTTP 401 verified live) — UNAVAILABLE directly, "
            "used via GDACS's aggregation instead.",
        ),
        HazardSourceStatus(
            hazard_type="THUNDERSTORM_PROXY", source="DAMINI (IITM/IMD)", is_authoritative=True,
            programmatically_accessible=False, status="UNAVAILABLE",
            reason="No public real-time lightning-detection API exists. A WMO-weather-code-based proxy (Open-Meteo) is used instead, clearly labeled as a proxy, never as real detection.",
        ),
        HazardSourceStatus(
            hazard_type="HIGH_WIND", source="Open-Meteo Weather", is_authoritative=False,
            programmatically_accessible=True, status="AVAILABLE",
            reason="Real, live, threshold-based on the existing Risk Engine's own WIND_SATURATION_MS constant.",
        ),
        HazardSourceStatus(
            hazard_type="HIGH_WAVES", source="Open-Meteo Marine", is_authoritative=False,
            programmatically_accessible=True, status="AVAILABLE",
            reason="Real, live, threshold-based on the existing Risk Engine's own WAVE_SATURATION_M constant.",
        ),
        HazardSourceStatus(
            hazard_type="GEOFENCE_BOUNDARY", source="ORCA GIS fixture (app.routing.fixtures)", is_authoritative=False,
            programmatically_accessible=True, status="LIMITED",
            reason="Real deterministic geometry, but explicitly illustrative/demo, not an authoritative legal maritime boundary (unchanged since Phase 1).",
        ),
    ]
    return {"data": {"sources": [s.model_dump(mode="json") for s in sources]}, "meta": {"generated_at": datetime.now(timezone.utc).isoformat()}, "errors": None}


@router.get("/safety/temporal")
def get_temporal_safety(
    latitude: float = Query(...),
    longitude: float = Query(...),
    hours: int = Query(default=6, ge=1, le=24),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
) -> dict:
    """Phase 7 (task §12): "will it be safe tomorrow morning?" — a real
    per-hour safety evaluation, NOT a duplicate temporal engine. Reuses
    `app.fishing.temporal.evaluate_temporal_suitability` VERBATIM (the
    exact same function `GET /fishing/temporal` already calls, itself the
    proven `parse_hourly_timeseries` workaround for the documented
    `requested_time`-ignored-by-single-value-agents bug — never
    reintroduced here) — every hour's real `safety_outcome`/
    `decision_outcome`/`risk_score`/`risk_level` was already computed by
    that one function; this endpoint only re-frames the SAME series around
    the safety question instead of the fishing-suitability one, and picks
    the best hour by lowest RISK (`select_best_time_by_risk`) rather than
    highest suitability.

    Explicit, honest limitations (task §13/§14 — never silently omitted):
    cyclone hazard presence is NOT evaluated per-hour (a live GDACS check
    reflects only the CURRENT moment — see `GET /safety/status` for that);
    authoritative lightning is UNAVAILABLE and only a coarse per-hour
    weather-code proxy is used (same as the single-instant path).
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
    best_index = select_best_time_by_risk(series)

    return {
        "data": {
            "latitude": latitude,
            "longitude": longitude,
            "series": [c.model_dump(mode="json") for c in series],
            "best_time_index": best_index,
        },
        "meta": {
            "hours_evaluated": hours,
            "temporal_resolution": "1 hour (Open-Meteo's native hourly cadence)",
            "is_forecast": True,
            "ranking": "lowest real risk score among hours that already passed the deterministic Safety Guard/Decision Engine — never selected by convenience or index",
            "limitations": [
                "Cyclone hazard presence is evaluated for the CURRENT moment only (GET /safety/status), not per forecast hour — a live GDACS check does not carry a per-hour track forecast this deployment can safely integrate.",
                "Authoritative lightning detection is UNAVAILABLE for this region (no public DAMINI/IMD API) — each hour's THUNDERSTORM_PROXY signal is a coarse Open-Meteo weather-code proxy, never real detection.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "app.fishing.temporal.evaluate_temporal_suitability (Phase 3/7)",
        },
        "errors": None,
    }
