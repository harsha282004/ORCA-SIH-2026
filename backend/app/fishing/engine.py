"""Fishing Intelligence Engine — Phase 3.

Composes EXISTING deterministic engines over MULTIPLE candidate points,
instead of the single point `app.agents.risk_suitability.agent
.RiskSuitabilityAgent` and the orchestration graph's `risk_suitability`
node already evaluate for a single query. No new risk formula, no new
suitability formula, no new safety formula: every candidate is scored by
calling the SAME `RiskSuitabilityAgent.evaluate`, the SAME
`derive_safety_facts`/`evaluate_safety_guard`, and the SAME `make_decision`
that `app.orchestration.nodes.OrchestrationNodes` already calls for one
point — looped over a bounded grid instead of one location.

Safety precedence (task requirement, architecture.md §23/§24's own
hierarchy, reused verbatim, not reinvented):

    SAFETY (Safety Guard outcome != PASS)     -> excluded from ranking
    GEOGRAPHIC (hard geofence boundary)       -> excluded from ranking (folds into Safety Guard's BLOCK_BOUNDARY)
    RISK (Decision Engine's HIGH-risk verdict) -> excluded unless Decision Engine itself allows it
    SUITABILITY (the engine's own score)       -> ranks what remains
    PREFERENCE/DISTANCE                        -> only breaks ties for "nearest suitable" queries

A candidate that fails ANY of the first three tiers lands in `avoid`, never
silently dropped — matching the task's explicit avoidance-analysis
requirement.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.environmental_sampling import SampleSite, sample_environment_grid
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.decision.engine import make_decision, risk_inputs_for_decision
from app.fishing.models import AreaComparisonResult, EnvironmentalContext, FishingCandidate, FishingCandidateSet
from app.gis.geofence import Geofence
from app.hazard.cyclone import fetch_active_cyclone_hazards, relevant_cyclones
from app.hazard.engine import detect_weather_hazards
from app.hazard.models import Hazard
from app.models.geo import BBox
from app.policy.safety_guard import derive_safety_facts, evaluate_safety_guard
from app.risk.config import RiskConfig
from app.suitability.engine import classify_suitability_category
from app.suitability.models import PFZReference

DEFAULT_SAMPLES_PER_AXIS = 6  # a deliberately small, bounded grid (36 points) — see module docstring's "no external-service hammering" note


def evaluate_candidate(
    *,
    site: SampleSite,
    geofences: list[Geofence],
    gis_agent: GISGeofencingAgent,
    risk_suitability_agent: RiskSuitabilityAgent,
    risk_config: RiskConfig,
    at_time: datetime,
    cyclone_hazards: list[Hazard] | None = None,
) -> FishingCandidate:
    """Evaluates ONE point using the exact same three deterministic steps
    `app.orchestration.nodes.OrchestrationNodes` runs for a single-point
    conversational query: Risk & Suitability -> Safety Guard -> Decision.

    Phase 4 hazard-awareness (task §18: "Fishing suitability: HIGH. But:
    Marine hazard: HIGH WIND. Safety decision: DO NOT RECOMMEND.") is
    entirely OPTIONAL and backward-compatible: `cyclone_hazards is None`
    (the default) reproduces Phase 3's exact behavior byte-for-byte —
    `has_active_high_severity_advisory` stays whatever `derive_safety_facts`
    itself computes. Passing the caller's already-fetched cyclone hazard
    list (ONE real fetch per `generate_candidates()` call, never one per
    candidate — see that function's own docstring) additionally runs the
    local, network-free `detect_weather_hazards` for THIS point's own
    weather/marine sample and overrides that one Safety Guard fact exactly
    the way `app.api.v1.safety._evaluate_safety` already does for a single
    point, so a high-suitability-but-hazardous candidate is correctly
    excluded from `ranked` via the SAME Safety Guard/Decision precedence,
    never a second, competing filter.
    """
    boundary_check = gis_agent.evaluate_point(site.latitude, site.longitude, geofences=geofences, at_time=at_time)
    distance_km = gis_agent.nearest_hard_geofence_distance_km(site.latitude, site.longitude, geofences=geofences, at_time=at_time)

    context = EnvironmentalContext(
        sea_surface_temperature_c=site.marine.data.get("sea_surface_temperature") if site.marine.status != "failed" else None,
        wave_height_m=site.marine.data.get("wave_height") if site.marine.status != "failed" else None,
        wave_direction_deg=site.marine.data.get("wave_direction") if site.marine.status != "failed" else None,
        wind_speed_ms=site.weather.data.get("wind_speed_10m") if site.weather.status != "failed" else None,
        ocean_current_velocity_ms=site.marine.data.get("ocean_current_velocity") if site.marine.status != "failed" else None,
    )

    result = risk_suitability_agent.evaluate(
        weather=site.weather,
        marine=site.marine,
        latitude=site.latitude,
        longitude=site.longitude,
        distance_to_zone_km=distance_km if distance_km is not None else 0.0,
        pfz_reference=PFZReference.unavailable(),
    )

    if result.status != "ok":
        return FishingCandidate(
            latitude=site.latitude,
            longitude=site.longitude,
            status="insufficient_data",
            reason=result.reason or "insufficient environmental data at this point",
            environmental_context=context,
            timestamp=at_time,
        )

    facts = derive_safety_facts(weather=site.weather, marine=site.marine, boundary_check=boundary_check, risk_suitability=result)

    active_hazards: list[Hazard] = []
    hazards_checked = cyclone_hazards is not None
    if hazards_checked:
        active_hazards = detect_weather_hazards(weather=site.weather, marine=site.marine, latitude=site.latitude, longitude=site.longitude)
        active_hazards += relevant_cyclones(cyclone_hazards, latitude=site.latitude, longitude=site.longitude)
        critical_hazard_active = any(h.severity in ("DANGER", "CRITICAL") for h in active_hazards)
        facts = facts.model_copy(update={"has_active_high_severity_advisory": critical_hazard_active})

    safety = evaluate_safety_guard(facts, min_confidence_threshold=risk_config.safety.min_confidence_threshold)
    risk_level, risk_score, confidence = risk_inputs_for_decision(result)
    decision = make_decision(
        risk_level=risk_level,
        risk_score=risk_score,
        confidence=confidence,
        min_confidence_threshold=risk_config.safety.min_confidence_threshold,
        safety_guard_result=safety,
        alternative_exists=False,
    )

    suitability = result.suitability_result
    is_safe = decision.outcome in ("RECOMMEND", "RECOMMEND_WITH_CAUTION")

    return FishingCandidate(
        latitude=site.latitude,
        longitude=site.longitude,
        status="ranked" if is_safe else "avoid",
        reason=None if is_safe else decision.reason,
        suitability_score=suitability.score if suitability else None,
        suitability_category=classify_suitability_category(suitability.score) if suitability else None,
        risk_score=result.risk_result.score if result.risk_result else None,
        risk_level=result.risk_result.level if result.risk_result else None,
        risk_factors=[f.model_dump(mode="json") for f in result.risk_result.factors] if result.risk_result else [],
        safety_outcome=safety.outcome,
        decision_outcome=decision.outcome,
        is_authoritative_restricted=bool(boundary_check.blocked and boundary_check.is_authoritative),
        confidence=result.confidence,
        environmental_context=context,
        active_hazards=[h.model_dump(mode="json") for h in active_hazards],
        active_hazards_checked=hazards_checked,
        timestamp=at_time,
    )


def generate_candidates(
    *,
    bbox: BBox,
    requested_time: datetime | None,
    weather_agent: WeatherIntelligenceAgent,
    oceanographic_agent: OceanographicIntelligenceAgent,
    gis_agent: GISGeofencingAgent,
    risk_suitability_agent: RiskSuitabilityAgent,
    risk_config: RiskConfig,
    samples_per_axis: int = DEFAULT_SAMPLES_PER_AXIS,
    max_concurrent_requests: int = 8,
    hazard_cache=None,
) -> FishingCandidateSet:
    """Generates and evaluates candidates across `bbox` — the exact same
    bounded sampling strategy the map's own suitability layer uses
    (`app.agents.environmental_sampling.sample_environment_grid`), never a
    live call per candidate cell.

    `hazard_cache` (Phase 4, optional, default None): when provided (an
    `app.agents.common.cache.AgentCache`-shaped object), active cyclone
    hazards are fetched EXACTLY ONCE for the whole call — never once per
    candidate, avoiding the N-times-external-service-hammering the task
    explicitly forbids — and passed to every `evaluate_candidate` so a
    candidate near an active cyclone is correctly excluded from `ranked`
    regardless of how favorable its wave/wind-based suitability looks.
    Omitting it reproduces Phase 3's exact behavior.
    """
    at_time = requested_time or datetime.now(timezone.utc)
    generated_at = datetime.now(timezone.utc)

    sites = sample_environment_grid(
        bbox=bbox,
        requested_time=at_time,
        samples_per_axis=samples_per_axis,
        max_concurrent_requests=max_concurrent_requests,
        weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent,
    )
    geofences, _metadata = gis_agent.get_geofences(bbox=bbox)

    cyclone_hazards: list[Hazard] | None = None
    if hazard_cache is not None:
        # Known, documented limitation (unlike `app.api.v1.safety`, which
        # surfaces a CYCLONE-UNAVAILABLE `HazardSourceStatus` and forces
        # `MarineSafetyLevel.UNKNOWN`): a GDACS outage here degrades to an
        # EMPTY cyclone list rather than blocking candidate generation —
        # `_tier` is available for a future report-back surface but not
        # propagated onto `FishingCandidateSet` yet. Weather/wave/wind
        # hazard detection (the common case) is unaffected either way.
        cyclone_hazards, _tier = fetch_active_cyclone_hazards(cache=hazard_cache)  # one real fetch, not per-candidate

    candidates = [
        evaluate_candidate(
            site=site, geofences=geofences, gis_agent=gis_agent, risk_suitability_agent=risk_suitability_agent,
            risk_config=risk_config, at_time=at_time, cyclone_hazards=cyclone_hazards,
        )
        for site in sites
    ]

    ranked, avoid = rank_candidates(candidates)

    return FishingCandidateSet(
        ranked=ranked,
        avoid=avoid,
        sample_count=len(candidates),
        ranked_count=len(ranked),
        avoid_count=len(avoid),
        requested_time=at_time,
        generated_at=generated_at,
        method=(
            f"{samples_per_axis}x{samples_per_axis} bounded environmental sampling grid (same strategy as "
            "GET /api/v1/layers/suitability); each candidate independently evaluated via the deterministic "
            "Risk & Suitability Agent, Safety Guard, and Decision Engine — the identical three-step pipeline "
            "app.orchestration.nodes.OrchestrationNodes runs for a single-point conversational query."
        ),
    )


def rank_candidates(
    candidates: list[FishingCandidate],
    *,
    min_suitability: float = 0.0,
    max_risk_score: float = 1.0,
) -> tuple[list[FishingCandidate], list[FishingCandidate]]:
    """Splits candidates into (ranked, avoid) — safety precedence enforced
    by construction, never by sorting alone: a candidate whose deterministic
    Decision outcome is not RECOMMEND/RECOMMEND_WITH_CAUTION (i.e. blocked
    by the Safety Guard, or HIGH risk with no safe alternative) can NEVER
    appear in `ranked`, regardless of how high its suitability score is —
    "a highly suitable area with unacceptable safety risk must not be
    recommended simply because suitability is high" (task requirement).
    """
    ranked: list[FishingCandidate] = []
    avoid: list[FishingCandidate] = []

    for c in candidates:
        if c.status != "ranked":
            avoid.append(c)
            continue
        if c.suitability_score is None or c.suitability_score < min_suitability:
            avoid.append(c.model_copy(update={"status": "avoid", "reason": f"suitability score below the requested minimum {min_suitability}"}))
            continue
        if c.risk_score is not None and c.risk_score > max_risk_score:
            avoid.append(c.model_copy(update={"status": "avoid", "reason": f"risk score above the requested maximum {max_risk_score}"}))
            continue
        ranked.append(c)

    ranked.sort(key=lambda c: c.suitability_score or 0.0, reverse=True)
    for i, c in enumerate(ranked):
        c.rank = i + 1

    return ranked, avoid


def find_nearest_suitable(
    ranked_candidates: list[FishingCandidate],
    *,
    origin_latitude: float,
    origin_longitude: float,
    gis_agent: GISGeofencingAgent,
) -> FishingCandidate | None:
    """"Nearest suitable" — nearest candidate among those that ALREADY
    passed safety/risk/suitability filtering (`ranked_candidates`, the
    output of `rank_candidates`), never the geographically nearest point
    full stop (task's own explicit definition).
    """
    if not ranked_candidates:
        return None

    best: FishingCandidate | None = None
    best_distance: float | None = None
    for c in ranked_candidates:
        distance = gis_agent.distance_km(origin_latitude, origin_longitude, c.latitude, c.longitude)
        if best_distance is None or distance < best_distance:
            best, best_distance = c, distance

    if best is not None:
        best = best.model_copy(update={"distance_km": best_distance})
    return best


def compare_candidates(candidates: list[FishingCandidate]) -> AreaComparisonResult:
    """Deterministic comparison — the "better" candidate is the highest-
    ranked (safest first, then highest suitability) among those actually
    eligible for ranking; a candidate excluded by safety/risk is never
    preferred over one that passed, regardless of its raw suitability
    number (same precedence `rank_candidates` already enforces).
    """
    generated_at = datetime.now(timezone.utc)
    eligible = [(i, c) for i, c in enumerate(candidates) if c.status == "ranked" and c.suitability_score is not None]

    if not eligible:
        return AreaComparisonResult(
            candidates=candidates,
            better_candidate_index=None,
            reason="none of the compared areas passed deterministic safety/risk filtering — no preference can be made between them",
            generated_at=generated_at,
        )

    best_index, best_candidate = max(eligible, key=lambda pair: pair[1].suitability_score or 0.0)
    reason = (
        f"candidate at index {best_index} has the highest ORCA Fishing Suitability score "
        f"({best_candidate.suitability_score:.3f}, {best_candidate.suitability_category}) among the areas that "
        f"passed deterministic safety and risk filtering"
    )
    return AreaComparisonResult(candidates=candidates, better_candidate_index=best_index, reason=reason, generated_at=generated_at)
