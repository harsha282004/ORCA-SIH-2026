"""Marine Intelligence Map layer endpoints — SIH Route Planner map.

Read-only GET endpoints exposing EXISTING deterministic ORCA engines (GIS
geofencing, the Risk Engine, the Fishing Suitability Engine) plus the real
live Weather/Oceanographic data agents as map layers. This module invents
NO new risk, suitability, hazard, or geofence LOGIC — it only serializes
what `app.gis` / `app.risk` / `app.suitability` / `app.agents.*` already
compute (the exact same code paths `POST /api/v1/route` and
`POST /api/v1/query` use) into GeoJSON/JSON a map can render.

    GET /layers/geofences     — GIS & Geofencing Agent's fixture set (STATIC, demo/illustrative — see app.agents.gis.agent)
    GET /layers/bathymetry    — static-dataset acquisition status (currently UNAVAILABLE — GEBCO not yet acquired)
    GET /layers/risk-surface  — deterministic Risk Engine over the SAME routing grid POST /api/v1/route optimizes against
    GET /layers/oceanography  — real Open-Meteo Marine/Weather samples: SST, waves, currents (+ explicit chlorophyll-unavailable)
    GET /layers/suitability   — deterministic Fishing Suitability Engine, sampled at the same points as oceanography

None of these call an LLM. None of them let the caller override a
deterministic result — every score/level/category here traces to the same
Risk/Suitability Engine code Phase 2/5 already shipped and tested.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.agents.environmental_provider import AgentBackedEnvironmentalProvider
from app.agents.environmental_sampling import sample_environment_grid
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import get_settings
from app.data.open_meteo_common import parse_hourly_timeseries
from app.data.open_meteo_marine import REQUIRED_HOURLY_PARAMETERS as MARINE_HOURLY_PARAMETERS
from app.data.open_meteo_marine import OpenMeteoMarineAdapter
from app.data.open_meteo_weather import REQUIRED_HOURLY_PARAMETERS as WEATHER_HOURLY_PARAMETERS
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter
from app.gis.grid import grid_dimensions
from app.models.contracts import SourceTier, TemporalValidityStatus
from app.risk.config import get_risk_config
from app.risk.engine import classify_risk_level
from app.routing.config import get_routing_config
from app.routing.grid import build_routing_grid
from app.suitability.config import get_suitability_weights
from app.suitability.engine import classify_suitability_category
from app.suitability.models import PFZReference

router = APIRouter()

# Phase 1 (Marine Data Foundation): where scripts/acquire_marine_data_
# foundation.py writes its processed, application-ready artifacts — see
# that script's own REPO_ROOT comment for why this is cwd-relative
# ("data/processed", matching Settings.data_raw_dir's own convention) and
# how the ./data:/app/data docker-compose volume mount makes this the same
# physical files the host repository tracks.
PROCESSED_DATA_DIR = Path.cwd() / "data" / "processed"


def _load_processed_geojson(filename: str) -> dict | None:
    """Reads an already-acquired, already-processed GeoJSON artifact from
    disk. Returns None (never a fabricated empty/sample FeatureCollection)
    if the file does not exist — the caller is responsible for reporting
    that honestly as UNAVAILABLE.
    """
    path = PROCESSED_DATA_DIR / filename
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

FreshnessStatus = Literal["CURRENT", "FORECAST", "CACHED", "STALE", "STATIC", "UNAVAILABLE"]


# --- Dependency providers — mirrors app.api.v1.route's own pattern so ---
# --- tests can override any of these with fast, offline fakes. ---------


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_weather_agent() -> WeatherIntelligenceAgent:
    return WeatherIntelligenceAgent()


def get_oceanographic_agent() -> OceanographicIntelligenceAgent:
    return OceanographicIntelligenceAgent()


def get_environmental_provider_class() -> type[AgentBackedEnvironmentalProvider]:
    return AgentBackedEnvironmentalProvider


def get_risk_suitability_agent(gis_agent: GISGeofencingAgent = Depends(get_gis_agent)) -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent(gis_agent=gis_agent, risk_config=get_risk_config(), suitability_weights=get_suitability_weights())


# --- Shared freshness classification ------------------------------------


def classify_freshness_status(
    *,
    temporal_validity_status: TemporalValidityStatus,
    source_tier: SourceTier,
    is_forecast: bool,
) -> FreshnessStatus:
    """Maps the ALREADY-computed Temporal Validity Gate verdict + source
    tier (architecture.md §16a/§17 — never recomputed here) onto the small
    display vocabulary the map's data-status panel needs. Purely a
    presentation-layer label, not a second freshness computation:
    `temporal_validity_status`/`source_tier`/`is_forecast` are read
    verbatim off the AgentResult(s) an agent already built.
    """
    if source_tier == "synthetic":
        return "STATIC"  # DEMO-mode fallback data — never presented as live (§16a)
    if temporal_validity_status in ("EXPIRED", "INVALID_TIMESTAMP", "MISSING_TIMESTAMP"):
        return "UNAVAILABLE"
    if temporal_validity_status == "STALE":
        return "STALE"
    if source_tier == "cached":
        return "CACHED"
    if is_forecast:
        # Open-Meteo's hourly value for "now" is still model output, not an
        # observed measurement (source_type="forecast" — see
        # app.data.open_meteo_weather/marine) — never mislabeled CURRENT.
        return "FORECAST"
    return "CURRENT"


def _worst(a: TemporalValidityStatus, b: TemporalValidityStatus) -> TemporalValidityStatus:
    from app.agents.common.result import worst_temporal_validity_status

    return worst_temporal_validity_status([a, b])


# --- GET /layers/geofences ------------------------------------------------


@router.get("/layers/geofences")
def get_geofences_layer(gis_agent: GISGeofencingAgent = Depends(get_gis_agent)) -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    geofences, metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)

    features = [
        {
            "type": "Feature",
            "properties": {
                "id": fence.id,
                "name": fence.name,
                "category": fence.category.value,
                "is_authoritative": fence.is_authoritative,
                "source": fence.source,
                "active_from": fence.active_from.isoformat() if fence.active_from else None,
                "active_to": fence.active_to.isoformat() if fence.active_to else None,
                "active_now": fence.is_active_at(now),
            },
            "geometry": {"type": "Polygon", "coordinates": [list(fence.geometry.exterior.coords)]},
        }
        for fence in geofences
    ]

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "layer": "geofences",
            "classification": "static",
            "status": "STATIC",
            "is_authoritative": metadata["is_authoritative"],
            "source_tier": metadata["source_tier"],
            "source": "ORCA GIS & Geofencing Agent (app.agents.gis.agent.GISGeofencingAgent)",
            "disclaimer": metadata["disclaimer"],
            "count": metadata["count"],
            "generated_at": now.isoformat(),
        },
        "errors": None,
    }


# --- GET /layers/bathymetry -----------------------------------------------


@router.get("/layers/bathymetry")
def get_bathymetry_layer(gis_agent: GISGeofencingAgent = Depends(get_gis_agent)) -> dict:
    now = datetime.now(timezone.utc)
    status = gis_agent.get_bathymetry_status()
    acquired = status.get("acquisition_status") == "acquired"

    if acquired:
        geojson = _load_processed_geojson("gebco_bathymetry_orca_bbox.geojson")
        if geojson is not None:
            acquisition_meta = status.get("metadata") or {}
            return {
                # Real GEBCO_2026 Grid depth samples, acquired via
                # scripts/acquire_marine_data_foundation.py (see
                # app.data.gebco's module docstring for the exact access
                # method) — every value here is a genuine WMS response
                # from GEBCO's own live service, never fabricated.
                "data": geojson,
                "meta": {
                    "layer": "bathymetry",
                    "classification": "static",
                    "status": "STATIC",
                    "available": True,
                    "source": status.get("source_name"),
                    "source_url": status.get("source_url"),
                    "dataset_version": status.get("dataset_version"),
                    "is_authoritative": status.get("is_authoritative"),
                    "acquired_at": status.get("acquired_at"),
                    "sample_count": acquisition_meta.get("sample_count_with_value"),
                    "depth_range_m": {"min": acquisition_meta.get("depth_min_m"), "max": acquisition_meta.get("depth_max_m")},
                    "depth_convention": "negative = below sea level, positive = land elevation (meters)",
                    "generated_at": now.isoformat(),
                },
                "errors": None,
            }

    return {
        # No depth geometry of any kind — GEBCO has not (yet) been
        # acquired for this deployment. Fabricating seabed depth is
        # explicitly disallowed by this task's own "real data only"
        # requirement.
        "data": None,
        "meta": {
            "layer": "bathymetry",
            "classification": "static",
            "status": "UNAVAILABLE",
            "available": False,
            "source": "GEBCO (configured target dataset — app.agents.gis.agent.KNOWN_STATIC_DATASETS)",
            "acquisition_status": status.get("acquisition_status"),
            "is_authoritative": status.get("is_authoritative"),
            "reason": status.get("reason")
            or "DATA INTEGRATION NOT CURRENTLY AVAILABLE — GEBCO bathymetry has not been acquired into this deployment. Run scripts/acquire_marine_data_foundation.py.",
            "generated_at": now.isoformat(),
        },
        "errors": None,
    }


# --- GET /layers/chlorophyll -----------------------------------------------


@router.get("/layers/chlorophyll")
def get_chlorophyll_layer(gis_agent: GISGeofencingAgent = Depends(get_gis_agent)) -> dict:
    """Real INCOIS Chlorophyll Concentration samples (app.data.incois_wms),
    acquired the same way as bathymetry — a periodic acquisition script,
    not a per-request live call, since INCOIS's own WMS exposes no time
    dimension (its current operational snapshot only; re-querying it on
    every map load would not yield a different value, only load their
    server unnecessarily — architecture.md's caching discipline).
    """
    now = datetime.now(timezone.utc)
    status = gis_agent.get_chlorophyll_status()
    acquired = status.get("acquisition_status") == "acquired"

    if acquired:
        geojson = _load_processed_geojson("incois_chl_orca_bbox.geojson")
        if geojson is not None:
            acquisition_meta = status.get("metadata") or {}
            return {
                "data": geojson,
                "meta": {
                    "layer": "chlorophyll",
                    "classification": "dynamic",
                    "status": "CURRENT",
                    "available": True,
                    "source": status.get("source_name"),
                    "source_url": status.get("source_url"),
                    "is_authoritative": status.get("is_authoritative"),
                    "acquired_at": status.get("acquired_at"),
                    "unit": "mg/m^3",
                    "unit_confidence": "inferred from value ranges and INCOIS's published PFZ methodology — see app.data.incois_wms module docstring",
                    "sample_count": acquisition_meta.get("sample_count_with_value"),
                    "value_range": {"min": acquisition_meta.get("value_min"), "max": acquisition_meta.get("value_max")},
                    "temporal_semantics": "INCOIS's current operational satellite ocean-colour snapshot — no historical time dimension is exposed by the source",
                    "generated_at": now.isoformat(),
                },
                "errors": None,
            }

    return {
        "data": None,
        "meta": {
            "layer": "chlorophyll",
            "classification": "dynamic",
            "status": "UNAVAILABLE",
            "available": False,
            "source": "INCOIS (chlorophyll not yet acquired)",
            "acquisition_status": status.get("acquisition_status"),
            "reason": status.get("reason")
            or "DATA INTEGRATION NOT CURRENTLY AVAILABLE — INCOIS chlorophyll has not been acquired into this deployment. Run scripts/acquire_marine_data_foundation.py.",
            "generated_at": now.isoformat(),
        },
        "errors": None,
    }


# --- GET /layers/risk-surface ---------------------------------------------


@router.get("/layers/risk-surface")
def get_risk_surface_layer(
    resolution_km: float | None = Query(default=None, gt=0),
    at: datetime | None = Query(default=None),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    provider_class=Depends(get_environmental_provider_class),
) -> dict:
    settings = get_settings()
    routing_config = get_routing_config()
    risk_config = get_risk_config()
    bbox = settings.demo_bbox
    resolution = resolution_km or routing_config.grid.resolution_km
    requested_time = at or datetime.now(timezone.utc)

    dims = grid_dimensions(bbox, resolution_km=resolution)
    total_cells = dims.n_rows * dims.n_cols
    if total_cells > routing_config.grid.max_cells:
        return {
            "data": None,
            "meta": None,
            "errors": [
                {
                    "code": "ROUTING_RESOURCE_LIMIT",
                    "message": f"grid would contain {total_cells} cells, exceeding max_cells={routing_config.grid.max_cells}",
                }
            ],
        }

    geofences, _geofence_metadata = gis_agent.get_geofences(bbox=bbox)

    # Identical construction to app.api.v1.route.create_route — the SAME
    # bounded live sampling, the SAME Risk Engine call. This heatmap is, by
    # construction, exactly what POST /api/v1/route optimizes its A* search
    # against, not a separately-invented "risk for display" computation.
    provider = provider_class(gis_agent=gis_agent, requested_time=requested_time, risk_config=risk_config)
    provider.prepare(bbox)

    nodes = build_routing_grid(
        bbox,
        resolution_km=resolution,
        geofences=geofences,
        risk_provider=provider.risk_provider,
        hazard_provider=provider.hazard_provider,
        at_time=requested_time,
    )

    features = []
    for node in nodes.values():
        properties: dict = {"cell_id": node.cell_id, "row": node.row, "col": node.col, "navigable": node.navigable}
        if node.navigable:
            properties.update(
                {
                    "risk_score": round(node.risk_score, 4) if node.risk_score is not None else None,
                    "risk_level": classify_risk_level(node.risk_score, risk_config.risk_thresholds)
                    if node.risk_score is not None
                    else None,
                    "hazard_score": round(node.hazard_score, 4) if node.hazard_score is not None else None,
                    "geofence_soft_penalty": round(node.geofence_soft_penalty, 4),
                }
            )
        else:
            properties["block_reason"] = node.block_reason
        features.append({"type": "Feature", "properties": properties, "geometry": node.cell.to_geojson()["geometry"]})

    status = classify_freshness_status(
        temporal_validity_status=provider.overall_temporal_validity,
        source_tier="synthetic" if provider.used_synthetic_fallback else "live",
        is_forecast=True,
    )

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "layer": "risk-surface",
            "classification": "derived",
            "status": status,
            "data_quality": "fixture" if provider.used_synthetic_fallback else "live",
            "confidence": round(provider.overall_confidence, 4),
            "temporal_validity_status": provider.overall_temporal_validity,
            "resolution_km": resolution,
            "cell_count": len(nodes),
            "requested_time": requested_time.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": (
                "ORCA deterministic Risk Engine (app.risk.engine.compute_risk) over bounded live "
                "Open-Meteo Weather+Marine sampling — the identical computation POST /api/v1/route uses"
            ),
            "risk_thresholds": {"low_max": risk_config.risk_thresholds.low_max, "moderate_max": risk_config.risk_thresholds.moderate_max},
        },
        "errors": None,
    }


# --- GET /layers/oceanography ---------------------------------------------


@router.get("/layers/oceanography")
def get_oceanography_layer(
    at: datetime | None = Query(default=None),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
) -> dict:
    settings = get_settings()
    requested_time = at or datetime.now(timezone.utc)

    sites = sample_environment_grid(
        bbox=settings.demo_bbox,
        requested_time=requested_time,
        samples_per_axis=settings.environmental_samples_per_axis,
        max_concurrent_requests=settings.max_concurrent_agent_requests,
        weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent,
    )

    features = []
    for site in sites:
        marine, weather = site.marine, site.weather
        if marine.status == "failed":
            properties = {"status": "UNAVAILABLE", "reason": "marine data unavailable for this sample point"}
        else:
            properties = {
                "status": classify_freshness_status(
                    temporal_validity_status=marine.temporal_validity_status,
                    source_tier=marine.source_tier,
                    is_forecast=bool(marine.temporal_validity.get("is_forecast", True)),
                ),
                "source": "open-meteo-marine",
                "source_tier": marine.source_tier,
                "confidence": round(marine.confidence, 4),
                "valid_from": marine.temporal_validity.get("valid_from"),
                "valid_to": marine.temporal_validity.get("valid_to"),
                "retrieved_at": marine.timestamp.isoformat(),
                "sea_surface_temperature_c": marine.data.get("sea_surface_temperature"),
                "wave_height_m": marine.data.get("wave_height"),
                "wave_direction_deg": marine.data.get("wave_direction"),
                "wave_period_s": marine.data.get("wave_period"),
                "ocean_current_velocity_ms": marine.data.get("ocean_current_velocity"),
                "ocean_current_direction_deg": marine.data.get("ocean_current_direction"),
                "weathercode": weather.data.get("weathercode") if weather.status != "failed" else None,
                # Phase 2 §9 — wind was already fetched by the Weather Agent
                # for every sample site (app.data.open_meteo_weather's own
                # REQUIRED_HOURLY_PARAMETERS) but never surfaced on this
                # endpoint's feature properties until now. No new call.
                "wind_speed_ms": weather.data.get("wind_speed_10m") if weather.status != "failed" else None,
                "wind_direction_deg": weather.data.get("wind_direction_10m") if weather.status != "failed" else None,
            }
        features.append(
            {"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": [site.longitude, site.latitude]}}
        )

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "layer": "oceanography",
            "classification": "dynamic",
            "source": (
                "Open-Meteo Marine API (sea_surface_temperature, wave_height/direction/period, "
                "ocean_current_velocity/direction) + Open-Meteo Weather API (weathercode) — "
                "app.data.open_meteo_marine / app.data.open_meteo_weather"
            ),
            "sample_count": len(features),
            "requested_time": requested_time.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chlorophyll": {
                "available": False,
                "reason": "Not part of Open-Meteo — see GET /api/v1/layers/chlorophyll for the real INCOIS chlorophyll integration.",
            },
        },
        # Phase 2 (Part A1) — INCOIS SST, acquired in Phase 1 but never
        # wired to a live endpoint until now. Extends this EXISTING
        # oceanography response (no new URL/route registered) rather than
        # adding a duplicate endpoint, per instruction — but kept as its
        # own top-level block, never merged into the `data`/`meta` pair
        # above, because it is a DIFFERENT provider (ESSO-INCOIS, not
        # Open-Meteo), a DIFFERENT representation (56 acquired WMS point
        # samples, not a live bounded fetch), and a DIFFERENT temporal
        # semantic (INCOIS's current operational snapshot, no per-request
        # freshness) — mixing them into one FeatureCollection would make
        # two provenances look like one, which Phase 2's own truthfulness
        # requirement forbids.
        "incois_sst": _incois_sst_block(gis_agent),
        "errors": None,
    }


def _incois_sst_block(gis_agent: GISGeofencingAgent) -> dict:
    now = datetime.now(timezone.utc)
    status = gis_agent.get_incois_sst_status()
    acquired = status.get("acquisition_status") == "acquired"

    if acquired:
        geojson = _load_processed_geojson("incois_sst_orca_bbox.geojson")
        if geojson is not None:
            acquisition_meta = status.get("metadata") or {}
            return {
                "data": geojson,
                "meta": {
                    "layer": "incois-sst",
                    "classification": "dynamic",
                    "status": "CURRENT",
                    "available": True,
                    "source": status.get("source_name"),
                    "source_url": status.get("source_url"),
                    "is_authoritative": status.get("is_authoritative"),
                    "acquired_at": status.get("acquired_at"),
                    "unit": "degC",
                    "unit_confidence": "inferred from value ranges and INCOIS's published PFZ methodology — see app.data.incois_wms module docstring",
                    "sample_count": acquisition_meta.get("sample_count_with_value"),
                    "value_range": {"min": acquisition_meta.get("value_min"), "max": acquisition_meta.get("value_max")},
                    "temporal_semantics": "INCOIS's current operational snapshot — no historical time dimension is exposed by the source",
                    "note": "A sparse, acquired sample set (see sample_count) — distinct from the live, denser Open-Meteo SST already in this response's primary `data`.",
                    "generated_at": now.isoformat(),
                },
                "errors": None,
            }

    return {
        "data": None,
        "meta": {
            "layer": "incois-sst",
            "classification": "dynamic",
            "status": "UNAVAILABLE",
            "available": False,
            "source": "INCOIS (SST not yet acquired)",
            "acquisition_status": status.get("acquisition_status"),
            "reason": status.get("reason")
            or "DATA INTEGRATION NOT CURRENTLY AVAILABLE — INCOIS SST has not been acquired into this deployment. Run scripts/acquire_marine_data_foundation.py.",
            "generated_at": now.isoformat(),
        },
        "errors": None,
    }


# --- GET /layers/suitability -----------------------------------------------


@router.get("/layers/suitability")
def get_suitability_layer(
    at: datetime | None = Query(default=None),
    weather_agent: WeatherIntelligenceAgent = Depends(get_weather_agent),
    oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_oceanographic_agent),
    suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
) -> dict:
    settings = get_settings()
    requested_time = at or datetime.now(timezone.utc)

    sites = sample_environment_grid(
        bbox=settings.demo_bbox,
        requested_time=requested_time,
        samples_per_axis=settings.environmental_samples_per_axis,
        max_concurrent_requests=settings.max_concurrent_agent_requests,
        weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent,
    )

    features = []
    for site in sites:
        result = suitability_agent.evaluate(
            weather=site.weather,
            marine=site.marine,
            latitude=site.latitude,
            longitude=site.longitude,
            distance_to_zone_km=0.0,
            pfz_reference=PFZReference.unavailable(),
        )
        if result.status != "ok":
            features.append(
                {
                    "type": "Feature",
                    "properties": {"status": "UNAVAILABLE", "reason": result.reason},
                    "geometry": {"type": "Point", "coordinates": [site.longitude, site.latitude]},
                }
            )
            continue

        suitability = result.suitability_result
        status = classify_freshness_status(
            temporal_validity_status=_worst(site.weather.temporal_validity_status, site.marine.temporal_validity_status),
            source_tier="synthetic" if "synthetic" in (site.weather.source_tier, site.marine.source_tier) else "live",
            is_forecast=True,
        )
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "status": status,
                    "label": suitability.label,
                    "score": round(suitability.score, 4),
                    "category": classify_suitability_category(suitability.score),
                    "risk_score": round(result.risk_result.score, 4),
                    "risk_level": result.risk_result.level,
                    "confidence": round(result.confidence, 4),
                    "components": {
                        "signal": round(suitability.components.signal, 4),
                        "safety": round(suitability.components.safety, 4),
                        "distance": round(suitability.components.distance, 4),
                        "data_confidence": round(suitability.components.data_confidence, 4),
                    },
                    "pfz_reference_status": suitability.pfz_reference.status,
                    "disclaimer": suitability.disclaimer,
                    "source": "ORCA Fishing Suitability Engine (app.suitability.engine.evaluate_suitability) via the Risk & Suitability Agent",
                },
                "geometry": {"type": "Point", "coordinates": [site.longitude, site.latitude]},
            }
        )

    return {
        "data": {"type": "FeatureCollection", "features": features},
        "meta": {
            "layer": "suitability",
            "classification": "derived",
            "source": "ORCA Fishing Suitability Engine (app.suitability.engine) — independent of, and never overriding, official INCOIS PFZ",
            "pfz_status": "unavailable",
            "sample_count": len(features),
            "requested_time": requested_time.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "errors": None,
    }


# --- GET /layers/marine-timeseries -----------------------------------------
#
# Phase 1 (Marine Data Foundation) — the genuine multi-timestep upgrade
# section 9/10/11 of that task ask for: every other endpoint in this module
# resolves ONE representative value per request (matching how
# app.agents.weather/oceanographic already work); this endpoint instead
# returns Open-Meteo's FULL hourly forecast series (all available
# timestamps in one response, not fabricated interpolation) for a single
# point, reusing the SAME adapters and unit-normalization pipeline, via the
# new, additive `parse_hourly_timeseries` function (app.data.open_meteo_common)
# — the existing single-value adapters/agents are completely unchanged.


@router.get("/layers/marine-timeseries")
def get_marine_timeseries(
    latitude: float = Query(...),
    longitude: float = Query(...),
) -> dict:
    settings = get_settings()
    if not settings.demo_bbox.contains(latitude, longitude):
        return {
            "data": None,
            "meta": None,
            "errors": [{"code": "OUT_OF_DOMAIN", "message": "requested point is outside the configured ORCA demo bbox"}],
        }

    weather_adapter = OpenMeteoWeatherAdapter(base_url=settings.open_meteo_weather_base_url, timeout_seconds=settings.http_timeout_seconds)
    marine_adapter = OpenMeteoMarineAdapter(base_url=settings.open_meteo_marine_base_url, timeout_seconds=settings.http_timeout_seconds)

    weather_raw = weather_adapter.fetch(latitude=latitude, longitude=longitude)
    marine_raw = marine_adapter.fetch(latitude=latitude, longitude=longitude)

    weather_records = parse_hourly_timeseries(weather_raw, parameters=WEATHER_HOURLY_PARAMETERS, source_name="open-meteo-weather")
    marine_records = parse_hourly_timeseries(marine_raw, parameters=MARINE_HOURLY_PARAMETERS, source_name="open-meteo-marine")

    all_records = weather_records + marine_records
    timestamps = sorted({r["timestamp"] for r in all_records})

    series = []
    for ts in timestamps:
        values = {r["parameter"]: (None if r["is_missing"] else r["value"]) for r in all_records if r["timestamp"] == ts}
        units = {r["parameter"]: r["unit"] for r in all_records if r["timestamp"] == ts}
        series.append({"timestamp": ts.isoformat(), "values": values, "units": units})

    now = datetime.now(timezone.utc)
    return {
        "data": {"latitude": latitude, "longitude": longitude, "series": series},
        "meta": {
            "layer": "marine-timeseries",
            "classification": "dynamic",
            "source": "Open-Meteo Weather + Marine APIs (app.data.open_meteo_weather / app.data.open_meteo_marine)",
            "variables": WEATHER_HOURLY_PARAMETERS + MARINE_HOURLY_PARAMETERS,
            "timestamp_count": len(series),
            "temporal_resolution": "1 hour (Open-Meteo's native hourly cadence)",
            "is_forecast": True,
            "retrieved_at": now.isoformat(),
            "generated_at": now.isoformat(),
        },
        "errors": None,
    }
