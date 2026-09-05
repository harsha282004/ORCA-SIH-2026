"""Shared builder for Phase 2's `NormalizedRiskComponents` from live agent
data — reused by both Phase 4's routing environmental provider
(`app.agents.environmental_provider`) and Phase 5's Risk & Suitability
Agent, so the extraction logic (which weather/marine field feeds which
risk factor) is written exactly once (Phase 5 task spec §40: "Do NOT
duplicate deterministic logic in LangGraph nodes").

Deliberately does not decide what "insufficient data" *means* — routing
needs a worst-case numeric fallback (A* cannot leave a cell's cost
undefined), while orchestration needs to surface it to the Safety Guard as
`has_critical_missing_data`, not invent a number. That policy choice stays
with each caller; this module only ever builds a complete, valid
`NormalizedRiskComponents` or raises.
"""
from __future__ import annotations

from app.agents.gis.agent import GISGeofencingAgent
from app.models.contracts import AgentResult
from app.risk.components import (
    COAST_DISTANCE_SATURATION_KM,
    RESTRICTED_ZONE_SATURATION_KM,
    advisory_or_hazard_risk,
    coast_distance_risk,
    data_confidence_penalty_risk,
    restricted_zone_distance_risk,
    wave_risk,
    wind_risk,
)
from app.risk.engine import NormalizedRiskComponents
from app.risk.hazard_proxies import lightning_thunderstorm_proxy


class InsufficientRiskDataError(ValueError):
    """Weather/marine data is not usable enough to build risk components."""


def build_normalized_risk_components(
    weather: AgentResult,
    marine: AgentResult,
    *,
    latitude: float,
    longitude: float,
    gis_agent: GISGeofencingAgent,
) -> NormalizedRiskComponents:
    if weather.status == "failed" or marine.status == "failed":
        raise InsufficientRiskDataError("weather or marine data unavailable")

    try:
        wave_height = marine.data["wave_height"]
        wind_speed = weather.data["wind_speed_10m"]
        weathercode = weather.data["weathercode"]
    except KeyError as exc:
        raise InsufficientRiskDataError(f"required parameter missing from agent data: {exc}") from exc

    # architecture.md §29: no official advisory ingestion exists yet (Phase
    # 4/5 do not implement it) and cyclone_proxy needs signals Phase 1's
    # adapters do not fetch — both honest, documented scope limitations.
    advisory_component = advisory_or_hazard_risk("none")

    hard_geofence_distance_km = gis_agent.nearest_hard_geofence_distance_km(latitude, longitude)
    # Documented simplification: no coastline-specific geometry exists
    # separate from the hard-geofence fixture set yet, so both
    # "restricted zone distance" and "coast distance" currently derive
    # from the same nearest-hard-geofence measurement.
    restricted_distance = (
        hard_geofence_distance_km if hard_geofence_distance_km is not None else RESTRICTED_ZONE_SATURATION_KM * 2
    )
    coast_distance = hard_geofence_distance_km if hard_geofence_distance_km is not None else COAST_DISTANCE_SATURATION_KM * 2

    confidence = min(weather.confidence, marine.confidence)

    return NormalizedRiskComponents(
        wave=wave_risk(wave_height),
        wind=wind_risk(wind_speed),
        advisory_or_hazard_flag=advisory_component,
        lightning_thunderstorm_proxy=lightning_thunderstorm_proxy(weathercode),
        restricted_zone_distance=restricted_zone_distance_risk(restricted_distance),
        coast_distance=coast_distance_risk(coast_distance),
        data_confidence_penalty=data_confidence_penalty_risk(confidence),
    )
