"""Temporal fishing suitability — Phase 3 §14/§15.

**Why this is a separate, lower-level path from `app.fishing.engine
.evaluate_candidate`**: that function calls `WeatherIntelligenceAgent
.get_weather(requested_time=...)` / `OceanographicIntelligenceAgent
.get_marine(requested_time=...)`, and a real, pre-existing property of
those agents was discovered while building this module — their underlying
`app.data.open_meteo_common.parse_hourly_observations` selects the hourly
step nearest `raw.retrieved_at` (the fetch's own wall-clock time), NOT the
caller's `requested_time`. That function's `requested_time` parameter
genuinely affects the CACHE KEY and the staleness/confidence computation,
but NOT which forecast hour's value comes back — so looping
`evaluate_candidate` over several `requested_time` values would fire
several real (wasteful) live HTTP calls that all return the SAME "current
hour" reading, silently failing to produce genuine per-hour variation.

This is a real, pre-existing, foundational-code property (used by every
single-point call across the whole system), out of Phase 3's scope to
change (see docs/PHASE_3_FISHING_INTELLIGENCE_REPORT.md's "Known
Limitations"). Instead, this module reuses the OTHER already-existing real
multi-hour path — `app.data.open_meteo_common.parse_hourly_timeseries`
(built in Phase 1 for `GET /api/v1/layers/marine-timeseries`), which DOES
return the genuine, distinct value for every real forecast hour from ONE
live fetch — and computes suitability/risk directly from the SAME
deterministic component functions `app.risk.components`/`app.risk.engine`
already define, at the SAME frozen weights (`app.risk.config
.get_risk_config`). No new formula; a lower-level (but equally real,
equally deterministic) composition of the exact same pieces.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.gis.agent import GISGeofencingAgent
from app.data.open_meteo_common import parse_hourly_timeseries
from app.data.open_meteo_marine import REQUIRED_HOURLY_PARAMETERS as MARINE_HOURLY_PARAMETERS
from app.data.open_meteo_marine import OpenMeteoMarineAdapter
from app.data.open_meteo_weather import REQUIRED_HOURLY_PARAMETERS as WEATHER_HOURLY_PARAMETERS
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter
from app.fishing.models import EnvironmentalContext, FishingCandidate
from app.policy.models import SafetyFacts
from app.policy.safety_guard import evaluate_safety_guard
from app.decision.engine import make_decision
from app.risk.components import (
    WAVE_SATURATION_M,
    WIND_SATURATION_MS,
    advisory_or_hazard_risk,
    coast_distance_risk,
    data_confidence_penalty_risk,
    restricted_zone_distance_risk,
    wave_risk,
    wind_risk,
)
from app.risk.config import RiskConfig
from app.risk.engine import NormalizedRiskComponents, compute_risk
from app.risk.hazard_proxies import lightning_thunderstorm_proxy
from app.suitability.config import SuitabilityWeights
from app.suitability.engine import classify_suitability_category, evaluate_suitability
from app.suitability.models import PFZReference

# Open-Meteo does not expose a separate confidence/uncertainty figure per
# forecast hour. Rather than compute a fabricated precision curve, this
# module uses one honest, documented constant for every hour — the SAME
# choice `app.reasoning.confidence` already makes for "no known
# disagreement" (see its own module docstring: "agreement = 1.0... not a
# claim of verified cross-source agreement"). Applied here as a Risk
# Engine data_confidence_penalty input, not silently omitted.
_FORECAST_CONFIDENCE = 0.85


def evaluate_temporal_suitability(
    *,
    latitude: float,
    longitude: float,
    hours: int,
    gis_agent: GISGeofencingAgent,
    risk_config: RiskConfig,
    suitability_weights: SuitabilityWeights,
    weather_adapter: OpenMeteoWeatherAdapter | None = None,
    marine_adapter: OpenMeteoMarineAdapter | None = None,
) -> list[FishingCandidate]:
    from app.config import get_settings

    settings = get_settings()
    weather_adapter = weather_adapter or OpenMeteoWeatherAdapter(
        base_url=settings.open_meteo_weather_base_url, timeout_seconds=settings.http_timeout_seconds
    )
    marine_adapter = marine_adapter or OpenMeteoMarineAdapter(
        base_url=settings.open_meteo_marine_base_url, timeout_seconds=settings.http_timeout_seconds
    )

    # ONE real live fetch each — the full real hourly series, not one call per hour.
    weather_raw = weather_adapter.fetch(latitude=latitude, longitude=longitude)
    marine_raw = marine_adapter.fetch(latitude=latitude, longitude=longitude)
    weather_records = parse_hourly_timeseries(weather_raw, parameters=WEATHER_HOURLY_PARAMETERS, source_name="open-meteo-weather")
    marine_records = parse_hourly_timeseries(marine_raw, parameters=MARINE_HOURLY_PARAMETERS, source_name="open-meteo-marine")

    by_timestamp: dict[datetime, dict[str, float | None]] = {}
    for r in weather_records + marine_records:
        by_timestamp.setdefault(r["timestamp"], {})[r["parameter"]] = None if r["is_missing"] else r["value"]

    now = datetime.now(timezone.utc)
    timestamps = sorted(ts for ts in by_timestamp if ts >= now.replace(minute=0, second=0, microsecond=0))[:hours]

    # Geofence distance is genuinely constant across the forecast window
    # (a point's distance to the nearest hard geofence does not change
    # hour to hour) — computed once, real, reused for every timestamp,
    # never recomputed as if it were time-varying.
    geofences, _metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)
    boundary_check = gis_agent.evaluate_point(latitude, longitude, geofences=geofences)
    distance_km = gis_agent.nearest_hard_geofence_distance_km(latitude, longitude, geofences=geofences)

    candidates: list[FishingCandidate] = []
    for ts in timestamps:
        values = by_timestamp.get(ts, {})
        wave_height = values.get("wave_height")
        wind_speed = values.get("wind_speed_10m")
        weathercode = values.get("weathercode")
        sst = values.get("sea_surface_temperature")

        if wave_height is None or wind_speed is None or weathercode is None:
            candidates.append(
                FishingCandidate(
                    latitude=latitude, longitude=longitude, status="insufficient_data",
                    reason="required hourly variable (wave height, wind speed, or weather code) missing for this forecast hour",
                    timestamp=ts,
                )
            )
            continue

        components = NormalizedRiskComponents(
            wave=wave_risk(wave_height),
            wind=wind_risk(wind_speed),
            advisory_or_hazard_flag=advisory_or_hazard_risk("none"),
            lightning_thunderstorm_proxy=lightning_thunderstorm_proxy(weathercode),
            restricted_zone_distance=restricted_zone_distance_risk(distance_km) if distance_km is not None else 0.0,
            coast_distance=coast_distance_risk(distance_km) if distance_km is not None else 0.0,
            data_confidence_penalty=data_confidence_penalty_risk(_FORECAST_CONFIDENCE),
        )
        risk_result = compute_risk(components, risk_config.risk_weights, risk_config.risk_thresholds)
        # Same documented proxy app.agents.risk_suitability.agent uses —
        # never a second, competing suitability formula.
        signal_score = 1.0 - risk_result.score
        suitability_result = evaluate_suitability(
            signal_score=signal_score,
            risk_score=risk_result.score,
            distance_to_zone_km=distance_km if distance_km is not None else 0.0,
            confidence=_FORECAST_CONFIDENCE,
            weights=suitability_weights,
            pfz_reference=PFZReference.unavailable(),
        )

        # Phase 4 hazard-awareness: this real per-hour wave/wind reading is
        # checked against the SAME Risk Engine saturation constants
        # `app.hazard.engine.detect_weather_hazards` uses for a single-point
        # query — no separate cyclone check here (a real cyclone's presence
        # is not part of the hourly Open-Meteo series this module already
        # fetches, and firing an additional live GDACS call per synthesized
        # hour would be exactly the "N-times external service" pattern the
        # task forbids; cyclone awareness is covered by
        # `app.fishing.engine`/`app.api.v1.safety` for the current-conditions
        # path). Previously hardcoded False (Phase 3) — this is the smallest
        # real wiring, not a new formula.
        hourly_hazard_active = wave_height >= WAVE_SATURATION_M or wind_speed >= WIND_SATURATION_MS
        facts = SafetyFacts(
            has_boundary_violation=bool(boundary_check.blocked),
            has_critical_missing_data=False,
            confidence=_FORECAST_CONFIDENCE,
            has_active_high_severity_advisory=hourly_hazard_active,
        )
        safety = evaluate_safety_guard(facts, min_confidence_threshold=risk_config.safety.min_confidence_threshold)
        decision = make_decision(
            risk_level=risk_result.level, risk_score=risk_result.score, confidence=_FORECAST_CONFIDENCE,
            min_confidence_threshold=risk_config.safety.min_confidence_threshold, safety_guard_result=safety,
            alternative_exists=False,
        )
        is_safe = decision.outcome in ("RECOMMEND", "RECOMMEND_WITH_CAUTION")

        candidates.append(
            FishingCandidate(
                latitude=latitude, longitude=longitude,
                status="ranked" if is_safe else "avoid",
                reason=None if is_safe else decision.reason,
                suitability_score=suitability_result.score,
                suitability_category=classify_suitability_category(suitability_result.score),
                risk_score=risk_result.score,
                risk_level=risk_result.level,
                risk_factors=[f.model_dump(mode="json") for f in risk_result.factors],
                safety_outcome=safety.outcome,
                decision_outcome=decision.outcome,
                is_authoritative_restricted=bool(boundary_check.blocked and boundary_check.is_authoritative),
                confidence=_FORECAST_CONFIDENCE,
                environmental_context=EnvironmentalContext(
                    sea_surface_temperature_c=sst, wave_height_m=wave_height, wind_speed_ms=wind_speed,
                ),
                timestamp=ts,
            )
        )

    return candidates


# Phase 7 (task §9/§12): a second, small selection helper over the SAME
# series `evaluate_temporal_suitability` already returns — reused by both
# `GET /fishing/temporal` (ranks by suitability, unchanged since Phase 3)
# and the new `GET /safety/temporal` (ranks by risk instead — a safety
# question cares about "lowest risk," not "highest fishing suitability").
# Both pools are drawn ONLY from `status == "ranked"` entries — i.e. ones
# that already passed the deterministic Safety Guard/Decision Engine —
# so safety precedence is enforced by construction, never by sorting alone
# (task §9's own worked example: a HIGH-risk hour is never selected merely
# because it happens to have a low index or high suitability).
def select_best_time_by_risk(series: list[FishingCandidate]) -> int | None:
    best_index: int | None = None
    best_score: float | None = None
    for i, c in enumerate(series):
        if c.status != "ranked" or c.risk_score is None:
            continue
        if best_score is None or c.risk_score < best_score:
            best_index, best_score = i, c.risk_score
    return best_index


def select_best_time_by_suitability(series: list[FishingCandidate]) -> int | None:
    """The exact selection `GET /fishing/temporal` has used since Phase 3
    (extracted here, unchanged, so `app.api.v1.query`'s conversational
    "best time to fish" handler reuses the identical logic rather than a
    second copy)."""
    best_index: int | None = None
    best_score: float | None = None
    for i, c in enumerate(series):
        if c.status == "ranked" and c.suitability_score is not None and (best_score is None or c.suitability_score > best_score):
            best_index, best_score = i, c.suitability_score
    return best_index
