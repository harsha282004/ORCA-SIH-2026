"""Alert Engine endpoint — architecture.md §29, §34 (`GET /alerts`,
"Active alerts for a region").

Computed on demand from the SAME Weather/Oceanographic/GIS/Risk-Suitability
agents the rest of ORCA uses (no second data path, no background poller —
none exists elsewhere in this architecture either, so this endpoint does
not introduce one). Deduplication/state (New/Updated/Escalated/Resolved)
is provided by comparing this call's detected hazards against the
previous call's, persisted per region in `app.alerts.store.AlertStore`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.alerts.engine import detect_hazard_severities, diff_alert_states
from app.alerts.models import AlertsResult
from app.alerts.store import AlertStore
from app.config import get_settings
from app.risk.config import get_risk_config
from app.services.cache import get_client as get_redis_client
from app.suitability.models import PFZReference

router = APIRouter()


def get_weather_agent() -> WeatherIntelligenceAgent:
    return WeatherIntelligenceAgent()


def get_oceanographic_agent() -> OceanographicIntelligenceAgent:
    return OceanographicIntelligenceAgent()


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_risk_suitability_agent() -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent()


def get_alert_store() -> AlertStore:
    settings = get_settings()
    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001 — client construction is lazy/local; never let it crash request handling
        client = None
    return AlertStore(client, ttl_seconds=settings.session_ttl_seconds)


def _region_key(latitude: float, longitude: float) -> str:
    # ~1.1km resolution (2 decimal degrees) — coarse enough that repeated
    # calls for "the same spot" (e.g. floating-point jitter from a UI map
    # click) hit the same dedup bucket, fine enough to distinguish
    # genuinely different demo-bbox locations.
    return f"{round(latitude, 2)}:{round(longitude, 2)}"


@router.get("/alerts")
def get_alerts(
    lat: float | None = Query(default=None, ge=-90.0, le=90.0),
    lon: float | None = Query(default=None, ge=-180.0, le=180.0),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    risk_suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    alert_store: AlertStore = Depends(get_alert_store),
) -> AlertsResult:
    settings = get_settings()
    if lat is not None and lon is not None:
        latitude, longitude = lat, lon
    else:
        latitude, longitude = settings.demo_bbox.center()

    weather = weather_agent.get_weather(latitude=latitude, longitude=longitude)
    marine = oceanographic_agent.get_marine(latitude=latitude, longitude=longitude)

    geofences, _metadata = gis_agent.get_geofences()
    distance_km = gis_agent.nearest_hard_geofence_distance_km(latitude, longitude, geofences=geofences)

    risk_suitability = risk_suitability_agent.evaluate(
        weather=weather,
        marine=marine,
        latitude=latitude,
        longitude=longitude,
        distance_to_zone_km=distance_km if distance_km is not None else 0.0,
        pfz_reference=PFZReference.unavailable(),
    )

    data_unavailable = risk_suitability.status != "ok"
    if data_unavailable:
        overall_score, overall_level = 0.0, "LOW"  # composite risk-threshold hazard skipped below, never guessed
    else:
        overall_score = risk_suitability.risk_result.score
        overall_level = risk_suitability.risk_result.level

    current = detect_hazard_severities(
        weather=weather,
        marine=marine,
        distance_to_hard_geofence_km=distance_km,
        overall_risk_score=overall_score,
        overall_risk_level=overall_level,
    )
    if data_unavailable:
        current.pop("risk_threshold", None)

    region_key = _region_key(latitude, longitude)
    previous = alert_store.get(region_key)
    risk_config = get_risk_config()
    alerts, next_state = diff_alert_states(previous=previous, current=current, thresholds=risk_config.risk_thresholds)
    alert_store.save(region_key, next_state)

    return AlertsResult(
        region_key=region_key, latitude=latitude, longitude=longitude, alerts=alerts, data_unavailable=data_unavailable
    )
