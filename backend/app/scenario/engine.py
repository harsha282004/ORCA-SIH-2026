"""Scenario Engine — architecture.md §32.

    1. Copy baseline state (never mutate it)
    2. Apply a perturbation to simulation-only parameters (e.g. wave_height + 1m)
    3. Re-run Fishing Suitability Engine + Risk Engine + Safety Guard on the perturbed state
    4. Diff against baseline
    5. Return both, clearly labeled

Every scoring step below calls the SAME functions the live orchestration
pipeline uses (`RiskSuitabilityAgent.evaluate`, `derive_safety_facts`,
`evaluate_safety_guard`, `risk_inputs_for_decision`, `make_decision`) — this
module contains no second copy of risk, safety, or decision logic, only the
perturb-then-re-score-twice control flow §32 itself describes.
"""
from __future__ import annotations

from app.agents.gis.agent import GISGeofencingAgent
from app.agents.query_understanding.models import IntentResult
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.decision.engine import make_decision, risk_inputs_for_decision
from app.gis.geofence import GeofenceCheckResult
from app.models.contracts import AgentResult
from app.policy.safety_guard import derive_safety_facts, evaluate_safety_guard
from app.risk.config import RiskConfig
from app.scenario.models import ScenarioPerturbation, ScenarioResult, ScenarioSnapshot
from app.suitability.models import PFZReference


def _bbox_centroid(bbox: dict) -> tuple[float, float]:
    return ((bbox["min_lat"] + bbox["max_lat"]) / 2.0, (bbox["min_lon"] + bbox["max_lon"]) / 2.0)


def _apply_perturbation(
    weather: AgentResult, marine: AgentResult, perturbation: ScenarioPerturbation
) -> tuple[AgentResult, AgentResult]:
    """Returns NEW `AgentResult` copies with simulation-only data fields
    shifted — `weather`/`marine` themselves are never mutated (§32 step 1).
    A physically-impossible negative result is floored at 0.0 (wave height
    and wind speed cannot be negative) — a physical bound, not a fabricated
    value.
    """
    perturbed_weather, perturbed_marine = weather, marine

    if perturbation.wind_speed_delta_ms is not None and "wind_speed_10m" in weather.data:
        new_value = max(0.0, weather.data["wind_speed_10m"] + perturbation.wind_speed_delta_ms)
        perturbed_weather = weather.model_copy(update={"data": {**weather.data, "wind_speed_10m": new_value}})

    if perturbation.wave_height_delta_m is not None and "wave_height" in marine.data:
        new_value = max(0.0, marine.data["wave_height"] + perturbation.wave_height_delta_m)
        perturbed_marine = marine.model_copy(update={"data": {**marine.data, "wave_height": new_value}})

    return perturbed_weather, perturbed_marine


def _score(
    *,
    weather: AgentResult,
    marine: AgentResult,
    latitude: float,
    longitude: float,
    distance_km: float,
    pfz_reference: PFZReference,
    boundary_check: GeofenceCheckResult,
    risk_suitability_agent: RiskSuitabilityAgent,
    risk_config: RiskConfig,
) -> ScenarioSnapshot:
    risk_suitability: RiskSuitabilityResult = risk_suitability_agent.evaluate(
        weather=weather,
        marine=marine,
        latitude=latitude,
        longitude=longitude,
        distance_to_zone_km=distance_km,
        pfz_reference=pfz_reference,
    )
    facts = derive_safety_facts(
        weather=weather, marine=marine, boundary_check=boundary_check, risk_suitability=risk_suitability
    )
    safety = evaluate_safety_guard(facts, min_confidence_threshold=risk_config.safety.min_confidence_threshold)

    risk_level, risk_score, confidence = risk_inputs_for_decision(risk_suitability)
    decision = make_decision(
        risk_level=risk_level,
        risk_score=risk_score,
        confidence=confidence,
        min_confidence_threshold=risk_config.safety.min_confidence_threshold,
        safety_guard_result=safety,
        alternative_exists=False,
    )
    return ScenarioSnapshot(risk_suitability=risk_suitability, safety=safety, decision=decision)


def run_scenario(
    *,
    intent: IntentResult,
    weather: AgentResult,
    marine: AgentResult,
    perturbation: ScenarioPerturbation,
    risk_suitability_agent: RiskSuitabilityAgent,
    gis_agent: GISGeofencingAgent,
    risk_config: RiskConfig,
) -> ScenarioResult:
    """`intent`/`weather`/`marine` are the prior turn's already-resolved
    baseline (from Session State — see `app.session.models.SessionState`'s
    `last_intent`/`last_weather_snapshot`/`last_marine_snapshot`); this
    function never fetches or invents new environmental data itself.
    """
    latitude, longitude = _bbox_centroid(intent.location["resolved_bbox"])
    geofences, _metadata = gis_agent.get_geofences()
    boundary_check = gis_agent.evaluate_point(latitude, longitude, geofences=geofences)
    distance_km = gis_agent.nearest_hard_geofence_distance_km(latitude, longitude, geofences=geofences)
    distance_km = distance_km if distance_km is not None else 0.0
    pfz_reference = PFZReference.unavailable()

    score_kwargs = dict(
        latitude=latitude,
        longitude=longitude,
        distance_km=distance_km,
        pfz_reference=pfz_reference,
        boundary_check=boundary_check,
        risk_suitability_agent=risk_suitability_agent,
        risk_config=risk_config,
    )
    baseline_snapshot = _score(weather=weather, marine=marine, **score_kwargs)

    perturbed_weather, perturbed_marine = _apply_perturbation(weather, marine, perturbation)
    scenario_snapshot = _score(weather=perturbed_weather, marine=perturbed_marine, **score_kwargs)

    return ScenarioResult(
        perturbation=perturbation,
        baseline=baseline_snapshot,
        scenario=scenario_snapshot,
        risk_score_delta=scenario_snapshot.decision.risk_score - baseline_snapshot.decision.risk_score,
        decision_changed=scenario_snapshot.decision.outcome != baseline_snapshot.decision.outcome,
        safety_outcome_changed=scenario_snapshot.safety.outcome != baseline_snapshot.safety.outcome,
    )
