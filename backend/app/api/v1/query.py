"""Conversational query endpoint — architecture.md §10 (orchestration
entrypoint), §31 (multi-turn session), §34 (response envelope).

    POST /api/v1/query {"query": "...", "session_id": "..."}
        -> runs the LangGraph orchestration graph
        -> persists conversational context (not environmental data) to the session
        -> returns {data, evidence, confidence, provenance, errors}

The LLM Provider is resolved once via `app.llm.factory.get_llm_provider`
inside the default `OrchestrationNodes()` — this endpoint itself never
imports a vendor SDK. `get_orchestration_nodes`/`get_session_store` are
FastAPI dependencies specifically so tests can override them with fast,
offline fakes (a `FakeLLMProvider`-backed node set, an in-memory session
store), the same pattern Phase 4's `/route` endpoint already established.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import get_settings
from app.decision.models import Decision
from app.fishing.engine import generate_candidates
from app.fishing.models import FishingCandidate
from app.fishing.temporal import evaluate_temporal_suitability, select_best_time_by_risk, select_best_time_by_suitability
from app.hazard.safety_status import classify_safety_status
from app.i18n.languages import is_supported
from app.llm.base import LLMConfigurationError
from app.orchestration.graph import build_orchestration_graph
from app.orchestration.nodes import OrchestrationNodes
from app.orchestration.state import OrchestrationState
from app.policy.models import SafetyGuardResult
from app.provenance.models import DecisionProvenanceGraph, RiskProvenance, RouteProvenance, ScenarioProvenance, SuitabilityProvenance
from app.scenario.engine import run_scenario
from app.scenario.models import ScenarioPerturbation
from app.provenance.store import ProvenanceStore
from app.risk.config import get_risk_config
from app.services.cache import get_client as get_redis_client
from app.session.models import SessionState
from app.session.store import SessionStore
from app.suitability.config import get_suitability_weights

router = APIRouter()


def get_orchestration_nodes() -> OrchestrationNodes:
    # architecture.md §38: a half-configured LLM layer is a deployment
    # error and must fail closed (never silently fall back to a fabricated
    # or degraded LLM) — this only changes HOW that failure is surfaced:
    # a structured {code, message} JSON body instead of FastAPI's opaque
    # default 500 text, which was otherwise indistinguishable from a real
    # crash to any API caller (Phase 11 QA finding).
    try:
        return OrchestrationNodes()
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "LLM_NOT_CONFIGURED", "message": str(exc)}
        ) from exc


def get_session_store() -> SessionStore:
    settings = get_settings()
    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001 — client construction is lazy/local; never let it crash request handling
        client = None
    return SessionStore(client, ttl_seconds=settings.session_ttl_seconds)


def get_fishing_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_fishing_weather_agent() -> WeatherIntelligenceAgent:
    return WeatherIntelligenceAgent()


def get_fishing_oceanographic_agent() -> OceanographicIntelligenceAgent:
    return OceanographicIntelligenceAgent()


def get_fishing_risk_suitability_agent(gis_agent: GISGeofencingAgent = Depends(get_fishing_gis_agent)) -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent(gis_agent=gis_agent, risk_config=get_risk_config(), suitability_weights=get_suitability_weights())


def get_fishing_hazard_cache():
    """Phase 4: the same Redis-backed `AgentCache` `app.api.v1.safety`/
    `app.api.v1.fishing` already use — one real GDACS fetch per
    zone_recommendation query, not per candidate. Wires Ask ORCA's
    zone_recommendation path into the SAME hazard-awareness
    `app.fishing.engine.generate_candidates` already supports.
    """
    from app.agents.common.cache import AgentCache

    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001
        client = None
    return AgentCache(client, ttl_seconds=1800)


def get_provenance_store() -> ProvenanceStore:
    settings = get_settings()
    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001 — client construction is lazy/local; never let it crash request handling
        client = None
    return ProvenanceStore(client, ttl_seconds=settings.session_ttl_seconds)


class QueryAPIRequest(BaseModel):
    query: str
    session_id: str | None = None
    # Phase 6 (task §32) — "Manual selection should override response
    # language, but MUST NOT change deterministic calculations." Applied
    # ONLY to which language the response/explanation is written in (see
    # its one use below, right after the graph produces `final_state`) —
    # intent classification, location/time resolution, and every
    # deterministic engine still run exactly as they would without it.
    # `None` (the default) is automatic detection, unchanged from Phase 1-5.
    language_override: str | None = None


class QueryAPIErrorResponse(BaseModel):
    code: str
    message: str


class QueryAPIResponse(BaseModel):
    data: dict | None = None
    evidence: list[dict] | None = None
    confidence: float | None = None
    provenance: dict | None = None
    errors: list[QueryAPIErrorResponse] | None = None
    session_id: str
    query_id: str


@router.post("/query")
def create_query(
    request: QueryAPIRequest,
    response: Response,
    nodes: OrchestrationNodes = Depends(get_orchestration_nodes),
    session_store: SessionStore = Depends(get_session_store),
    provenance_store: ProvenanceStore = Depends(get_provenance_store),
    fishing_gis_agent: GISGeofencingAgent = Depends(get_fishing_gis_agent),
    fishing_weather_agent: WeatherIntelligenceAgent = Depends(get_fishing_weather_agent),
    fishing_oceanographic_agent: OceanographicIntelligenceAgent = Depends(get_fishing_oceanographic_agent),
    fishing_risk_suitability_agent: RiskSuitabilityAgent = Depends(get_fishing_risk_suitability_agent),
    fishing_hazard_cache=Depends(get_fishing_hazard_cache),
) -> QueryAPIResponse:
    if not request.query or not request.query.strip():
        response.status_code = 422
        return QueryAPIResponse(
            errors=[QueryAPIErrorResponse(code="EMPTY_QUERY", message="query must not be empty")],
            session_id=request.session_id or "",
            query_id="",
        )

    session = session_store.get_or_create(request.session_id)

    graph = build_orchestration_graph(nodes)
    initial_state = OrchestrationState(
        query=request.query,
        session_id=session.session_id,
        language=session.last_language,
        prior_intent=session.last_intent,
        # Phase 6 (task §13/§18) — the exact point last discussed (a
        # fishing candidate, a route endpoint, a safety-check location),
        # more specific than `prior_intent.location`'s whole named-place
        # bbox. See app.agents.query_understanding.reference
        # .resolve_reference's own docstring for how this is used.
        prior_selection=session.last_selected_point,
    )
    raw_result = graph.invoke(initial_state)
    final_state = OrchestrationState.model_validate(raw_result)

    # Phase 6 (task §32): the manual language override, applied here and
    # ONLY here — after every deterministic step (intent, location, time,
    # risk, safety, decision, route) has already run using the query's own
    # detected language. This changes nothing but which language the
    # Evidence & Explanation Agent (below, and inside
    # `_handle_zone_recommendation`/`_handle_conversational_followup`)
    # writes its response in.
    if request.language_override is not None and is_supported(request.language_override):
        final_state = final_state.model_copy(update={"language": request.language_override})

    # Phase 7 (task §4/§21/§25): a WHAT-IF scenario request — checked
    # BEFORE the Phase 6 follow-up-reuse path below, since a scenario query
    # ("what if waves reach 3m there?") may ALSO carry `refers_to_prior`/
    # `selection_reference` but means something structurally different
    # (perturb-then-rescore, never a stored-result replay).
    scenario_response = _handle_scenario_query(
        final_state=final_state, session=session, evidence_agent=EvidenceExplanationAgent(),
        gis_agent=fishing_gis_agent, risk_suitability_agent=fishing_risk_suitability_agent, risk_config=get_risk_config(),
    )
    if scenario_response is not None:
        session.turn_count += 1
        session.last_query = request.query
        session.last_language = final_state.language
        if final_state.intent is not None:
            session.last_intent = final_state.intent
        session_store.save(session)
        if scenario_response.provenance is not None:
            provenance_store.save(scenario_response.provenance)
        return QueryAPIResponse(
            data=scenario_response.data, evidence=scenario_response.evidence, confidence=scenario_response.confidence,
            provenance=scenario_response.provenance.model_dump(mode="json") if scenario_response.provenance else None,
            session_id=session.session_id, query_id=final_state.query_id,
        )

    # Phase 6 (task §17): a follow-up that names a SPECIFIC previously-
    # returned option ("what about the alternative route?", "which is
    # safer?") is answered by REUSING the already-computed structured
    # result from the session — never a second deterministic computation —
    # BEFORE falling through to the normal (fresh) handling below. Checked
    # first because it can short-circuit the whole rest of this function.
    followup_response = _handle_conversational_followup(
        final_state=final_state, session=session, evidence_agent=EvidenceExplanationAgent(),
    )
    if followup_response is not None:
        session.turn_count += 1
        session.last_query = request.query
        session.last_language = final_state.language
        if final_state.intent is not None:
            session.last_intent = final_state.intent
        session_store.save(session)
        if followup_response.provenance is not None:
            provenance_store.save(followup_response.provenance)
        return QueryAPIResponse(
            data=followup_response.data,
            evidence=followup_response.evidence,
            confidence=followup_response.confidence,
            provenance=followup_response.provenance.model_dump(mode="json") if followup_response.provenance else None,
            session_id=session.session_id,
            query_id=final_state.query_id,
        )

    session.turn_count += 1
    session.last_query = request.query
    session.last_language = final_state.language
    if final_state.intent is not None:
        session.last_intent = final_state.intent
    if final_state.decision is not None:
        session.last_decision = final_state.decision
    if final_state.provenance is not None:
        session.last_provenance = final_state.provenance
    if final_state.weather is not None:
        session.last_weather_snapshot = final_state.weather
    if final_state.marine is not None:
        session.last_marine_snapshot = final_state.marine
    # Phase 6 (task §13/§14) — remember the exact point this turn actually
    # discussed, so a follow-up naming no new place ("is it still safe?")
    # can re-anchor precisely rather than falling back to a whole region.
    #
    # Only overwrites when THIS turn resolved a genuinely specific place
    # (`location.type != "region"`) — a query that itself named no place
    # (e.g. a region-wide "is it safe today?") is not more specific context
    # than whatever was already remembered, and must not clobber a
    # precisely-anchored prior point (a fishing candidate's exact
    # coordinate, say) with the whole demo region's centroid. This was a
    # real bug, caught live: a Kannada follow-up the LLM did NOT recognize
    # as `refers_to_prior` (a genuine, disclosed LLM-reliability limitation
    # — see the Phase 6 report §7/§23) fell through to this normal path and
    # would otherwise have overwritten the previous turn's precise "Area A"
    # anchor with the generic region centroid, breaking every SUBSEQUENT
    # follow-up in the same conversation too.
    if (
        final_state.intent is not None
        and final_state.latitude is not None
        and final_state.longitude is not None
        and final_state.intent.location.get("type") != "region"
    ):
        session.last_selected_point = {
            "latitude": final_state.destination_latitude if final_state.route is not None and final_state.destination_latitude is not None else final_state.latitude,
            "longitude": final_state.destination_longitude if final_state.route is not None and final_state.destination_longitude is not None else final_state.longitude,
            "label": final_state.intent.location.get("name", "the previous location"),
            "source": final_state.intent.intent_class,
        }
    if final_state.route is not None:
        primary_option = _route_option_summary(
            label="A", route=final_state.route, decision=final_state.decision, safety=final_state.safety, hazards=final_state.route_hazards,
        )
        session.last_route_options = [primary_option] + [
            _route_option_summary_from_ranked(alt) for alt in final_state.route_alternatives
        ]
        session.last_route_comparison = final_state.route_comparison
    session_store.save(session)

    if final_state.provenance is not None:
        provenance_store.save(final_state.provenance)

    if final_state.status == "clarification_needed":
        return QueryAPIResponse(
            data={"status": "clarification_needed", "clarification": final_state.clarification.model_dump(mode="json")},
            session_id=session.session_id,
            query_id=final_state.query_id,
        )

    # Phase 7 (task §8/§9/§10): "which time is better?", "best time to fish
    # tomorrow?" — a real multi-hour window, not the single instant the
    # graph above already resolved. Checked before zone_recommendation
    # (below) so a temporal zone_recommendation query ("when's the best
    # time to fish near Mangaluru tomorrow?") gets the WINDOW answer, not
    # the single-instant candidate list.
    if (
        final_state.intent is not None
        and final_state.intent.wants_temporal_window
        and not final_state.intent.is_scenario
        and final_state.intent.intent_class in ("safety_check", "zone_recommendation")
        and final_state.latitude is not None
        and final_state.longitude is not None
    ):
        temporal_response = _handle_temporal_window_query(
            final_state=final_state, gis_agent=fishing_gis_agent, evidence_agent=EvidenceExplanationAgent(),
        )
        if temporal_response is not None:
            session.last_provenance = temporal_response.provenance if temporal_response.provenance else session.last_provenance
            session_store.save(session)
            if temporal_response.provenance is not None:
                provenance_store.save(temporal_response.provenance)
            return QueryAPIResponse(
                data=temporal_response.data, evidence=temporal_response.evidence, confidence=temporal_response.confidence,
                provenance=temporal_response.provenance.model_dump(mode="json") if temporal_response.provenance else None,
                session_id=session.session_id, query_id=final_state.query_id,
            )

    # Phase 3 — Fishing Intelligence: "zone_recommendation" is a query
    # SHAPE the single-point graph above cannot answer (it evaluates one
    # centroid; this needs many candidates ranked against each other).
    # Deliberately NOT a new graph node — composed here, at the API layer,
    # exactly like POST /api/v1/route already composes a deterministic
    # engine outside the graph. The graph above still ran query_understanding
    # (the ONE real LLM call this turn needs for intent + language) and its
    # own single-point analysis; only the response is overridden below with
    # the genuinely multi-candidate deterministic result, and the SAME
    # Evidence & Explanation Agent explains it — never a second, competing
    # LLM call and never an LLM-invented recommendation.
    if final_state.intent is not None and final_state.intent.intent_class == "zone_recommendation":
        fishing_response = _handle_zone_recommendation(
            final_state=final_state,
            gis_agent=fishing_gis_agent,
            weather_agent=fishing_weather_agent,
            oceanographic_agent=fishing_oceanographic_agent,
            risk_suitability_agent=fishing_risk_suitability_agent,
            evidence_agent=EvidenceExplanationAgent(),  # same construction the graph's own evidence node uses (app.orchestration.nodes.OrchestrationNodes.__init__)
            hazard_cache=fishing_hazard_cache,
        )
        if fishing_response is not None:
            if fishing_response.provenance is not None:
                session.last_provenance = fishing_response.provenance
            # Phase 6 (task §13/§14) — the TOP candidate's own coordinate,
            # not the whole demo region the single-point graph above
            # evaluated, is "the place ORCA just discussed" for a fishing
            # follow-up ("what about the waves there?"). `last_fishing
            # _candidates` is the compact ranked-candidate list a
            # "which is safest?"/"compare" follow-up reuses without
            # recomputing (task §17).
            ranked = fishing_response.data.get("fishing_candidates", {}).get("ranked") or []
            if ranked:
                top = ranked[0]
                session.last_selected_point = {
                    "latitude": top["latitude"], "longitude": top["longitude"],
                    "label": "Area A", "source": "zone_recommendation",
                }
                session.last_fishing_candidates = [
                    {
                        "label": chr(ord("A") + i), "latitude": c["latitude"], "longitude": c["longitude"],
                        "risk_level": c.get("risk_level"), "risk_score": c.get("risk_score"),
                        "suitability_score": c.get("suitability_score"), "suitability_category": c.get("suitability_category"),
                        "decision_outcome": c.get("decision_outcome"), "safety_outcome": c.get("safety_outcome"),
                        "confidence": c.get("confidence"),
                        "environmental_context": c.get("environmental_context"),
                    }
                    for i, c in enumerate(ranked)
                ]
            session_store.save(session)
            if fishing_response.provenance is not None:
                provenance_store.save(fishing_response.provenance)
            return QueryAPIResponse(
                data=fishing_response.data,
                evidence=fishing_response.evidence,
                confidence=fishing_response.confidence,
                provenance=fishing_response.provenance.model_dump(mode="json") if fishing_response.provenance else None,
                session_id=session.session_id,
                query_id=final_state.query_id,
            )

    evidence = []
    if final_state.weather is not None:
        evidence.extend(e.model_dump(mode="json") for e in final_state.weather.evidence)
    if final_state.marine is not None:
        evidence.extend(e.model_dump(mode="json") for e in final_state.marine.evidence)

    # Phase 4: the same real hazard detection every conversational intent
    # now runs (via the shared `safety_guard` node) surfaced in the
    # response — never LLM-invented, never silently dropped when empty.
    # Phase 5: for a route_planning query that actually computed a route,
    # `final_state.decision`/`.safety` were overridden with the ROUTE's own
    # values (see `OrchestrationNodes.route`) — the hazards shown here must
    # be the SAME route's hazards (`route_hazards`), never the origin
    # point's separate hazard check, to avoid mixing two different
    # evaluations in one `marine_safety` block.
    hazards_for_status = final_state.route_hazards if final_state.route is not None else final_state.hazards
    marine_safety_level, marine_safety_reason = classify_safety_status(
        decision=final_state.decision, safety=final_state.safety,
        hazards=hazards_for_status, unavailable_sources=final_state.hazard_unavailable_sources,
    )

    data = {
        "status": final_state.status,
        "language": final_state.language,
        "decision": final_state.decision.model_dump(mode="json") if final_state.decision else None,
        "safety": final_state.safety.model_dump(mode="json") if final_state.safety else None,
        "explanation": final_state.explanation.rationale if final_state.explanation else None,
        "used_fallback_template": final_state.explanation.used_fallback_template if final_state.explanation else None,
        "route_note": final_state.route_note,
        "marine_safety": {
            "level": marine_safety_level,
            "reason": marine_safety_reason,
            "hazards": [h.model_dump(mode="json") for h in hazards_for_status],
            "unavailable_sources": [s.model_dump(mode="json") for s in final_state.hazard_unavailable_sources],
        },
        # Phase 5 (task §28) — present only when the `route` node actually
        # computed a real route this turn (a route_planning query naming a
        # resolvable destination); `None` for every other intent/outcome,
        # never a fabricated empty route.
        "route": final_state.route.model_dump(mode="json") if final_state.route is not None else None,
        "route_alternatives": final_state.route_alternatives,
        "route_comparison": final_state.route_comparison,
    }

    return QueryAPIResponse(
        data=data,
        evidence=evidence,
        confidence=final_state.decision.confidence if final_state.decision else None,
        provenance=final_state.provenance.model_dump(mode="json") if final_state.provenance else None,
        session_id=session.session_id,
        query_id=final_state.query_id,
    )


class _FishingQueryResponse(BaseModel):
    data: dict
    evidence: list[dict] | None
    confidence: float | None
    provenance: DecisionProvenanceGraph | None


# --- Phase 7: conversational what-if scenarios (task §4/§17-§22/§25) -------
#
# USER -> Query Understanding (identifies variable + explicit numeric
# target only — task §4's own diagram) -> HERE: real baseline (the SAME
# weather/marine the graph already fetched fresh, at whatever location
# Phase 6's `resolve_reference` already anchored this turn to) ->
# `app.scenario.engine.run_scenario` (UNCHANGED, existing, reused verbatim
# — perturbs, then re-runs the EXISTING Risk/Suitability/Safety/Decision
# pipeline exactly twice) -> Evidence -> Groq explains ONLY. No
# `ScenarioRiskEngine`/`ScenarioSafetyEngine` exists or is created here.

_SCENARIO_VARIABLE_LABEL = {"wave_height": "wave height", "wind_speed": "wind speed"}
_SCENARIO_VARIABLE_UNIT = {"wave_height": "m", "wind_speed": "m/s"}


def _handle_scenario_query(
    *, final_state: OrchestrationState, session: SessionState, evidence_agent: EvidenceExplanationAgent,
    gis_agent: GISGeofencingAgent, risk_suitability_agent: RiskSuitabilityAgent, risk_config,
) -> _FishingQueryResponse | None:
    intent = final_state.intent
    if intent is None or not intent.is_scenario:
        return None

    # --- Underspecified scenario: ask, never guess (task §17/§32) ----------
    if intent.scenario_variable is None or intent.scenario_target_value is None:
        data = {
            "status": "completed",
            "language": final_state.language,
            "explanation": (
                "ORCA currently supports what-if scenarios for wave height (in metres) and wind speed (in "
                "metres/second) only — for example, \"what if wave height increases to 3.5 metres?\". Please name "
                "one of these two variables with a specific number."
            ),
            "used_fallback_template": True,
            "scenario": None,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    # --- Real baseline required (task §29/§31 — never invented, never stale) ---
    weather, marine = final_state.weather, final_state.marine
    if weather is None or marine is None or weather.status == "failed" or marine.status == "failed":
        data = {
            "status": "completed", "language": final_state.language,
            "explanation": "Scenario assessment unavailable: no valid real baseline environmental data could be resolved for this location.",
            "used_fallback_template": True, "scenario": None,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    if weather.temporal_validity_status in ("STALE", "EXPIRED") or marine.temporal_validity_status in ("STALE", "EXPIRED"):
        data = {
            "status": "completed", "language": final_state.language,
            "explanation": "Scenario assessment unavailable because the underlying marine data is stale.",
            "used_fallback_template": True, "scenario": None,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    variable = intent.scenario_variable
    baseline_value = marine.data.get("wave_height") if variable == "wave_height" else weather.data.get("wind_speed_10m")
    if baseline_value is None:
        data = {
            "status": "completed", "language": final_state.language,
            "explanation": f"Scenario assessment unavailable: no real baseline {_SCENARIO_VARIABLE_LABEL[variable]} value is available for this location.",
            "used_fallback_template": True, "scenario": None,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    delta = intent.scenario_target_value - baseline_value
    perturbation = ScenarioPerturbation(
        wave_height_delta_m=delta if variable == "wave_height" else None,
        wind_speed_delta_ms=delta if variable == "wind_speed" else None,
    )

    result = run_scenario(
        intent=intent, weather=weather, marine=marine, perturbation=perturbation,
        risk_suitability_agent=risk_suitability_agent, gis_agent=gis_agent, risk_config=risk_config,
    )

    br = result.baseline.risk_suitability.risk_result
    sr = result.scenario.risk_suitability.risk_result
    scenario_provenance = ScenarioProvenance(
        variable=f"{variable}_m" if variable == "wave_height" else f"{variable}_ms",
        unit=_SCENARIO_VARIABLE_UNIT[variable], baseline_value=baseline_value, scenario_value=intent.scenario_target_value,
        baseline_risk_score=br.score if br else 0.0, scenario_risk_score=sr.score if sr else 0.0,
        baseline_decision_outcome=result.baseline.decision.outcome, scenario_decision_outcome=result.scenario.decision.outcome,
    )
    provenance = DecisionProvenanceGraph(
        query_id=final_state.query_id,
        risk=RiskProvenance(factors=sr.factors if sr else [], score=sr.score if sr else 0.0, level=sr.level if sr else "HIGH"),
        scenario=scenario_provenance, safety=result.scenario.safety, decision=result.scenario.decision,
        generated_at=datetime.now(timezone.utc),
    )
    explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=intent.persona or "fisherman")

    # A route-endpoint scenario is disclosed as such — this evaluates the
    # deterministic Risk/Safety impact AT the route's own endpoint, never a
    # full route re-plan with perturbed conditions (task §22's own explicit
    # "if the existing engine cannot support the scenario reliably, return a
    # limitation instead of fabricating" — a full perturbed re-route was
    # judged out of this phase's bounded scope; see the Phase 7 report).
    scope_note = None
    if session.last_selected_point and session.last_selected_point.get("source") == "route_planning":
        scope_note = (
            "This evaluates conditions AT the route's own destination point using the same deterministic Risk/"
            "Safety pipeline — it does not re-plan the full route or its alternatives under the changed condition."
        )

    data = {
        "status": "completed",
        "language": final_state.language,
        "explanation": explanation.rationale,
        "used_fallback_template": explanation.used_fallback_template,
        "scenario": {
            "label": result.label,
            "variable": variable,
            "unit": _SCENARIO_VARIABLE_UNIT[variable],
            "baseline_value": baseline_value,
            "scenario_value": intent.scenario_target_value,
            "delta": delta,
            "assumption": f"{_SCENARIO_VARIABLE_LABEL[variable]} manually changed from {baseline_value:.2f} to {intent.scenario_target_value:.2f} {_SCENARIO_VARIABLE_UNIT[variable]} — a user-specified assumption, not an actual forecast.",
            "scope_note": scope_note,
            "baseline": result.baseline.model_dump(mode="json"),
            "scenario_result": result.scenario.model_dump(mode="json"),
            "risk_score_delta": result.risk_score_delta,
            "decision_changed": result.decision_changed,
            "safety_outcome_changed": result.safety_outcome_changed,
        },
    }
    return _FishingQueryResponse(data=data, evidence=None, confidence=result.scenario.decision.confidence, provenance=provenance)


# --- Phase 6: conversational follow-up reuse (task §17/§18/§30) -----------
#
# "Reuse previous structured route results where valid. Recalculate when
# current conditions/time require it." A follow-up naming a SPECIFIC
# already-returned option (`selection_reference`) or asking to compare
# options (`operation == "compare"`) is answered from the compact summary
# already stored in `SessionState` by the ORIGINAL turn that computed it —
# never a second `generate_route_alternatives`/`generate_candidates` call.
# This is deliberately narrow: any follow-up that is NOT recognized here
# (returns `None`) falls through to the caller's normal, always-fresh
# handling — the safe default (task §15's "context is not authority").


def _route_option_summary(*, label: str, route, decision, safety, hazards) -> dict:
    """A compact (no path geometry) summary of one route option — task
    §14's "do not store excessive conversation history" applied to routes.
    """
    return {
        "label": label,
        "latitude": route.destination.latitude,
        "longitude": route.destination.longitude,
        "distance_km": route.metrics.total_distance_km,
        "total_cost": route.metrics.total_cost,
        "risk_level": decision.risk_level if decision else None,
        "risk_score": decision.risk_score if decision else None,
        "confidence": route.confidence,
        "decision_outcome": decision.outcome if decision else None,
        "decision_reason": decision.reason if decision else None,
        "safety_outcome": safety.outcome if safety else None,
        "safety_reason": safety.reason if safety else None,
        "hazard_count": len(hazards) if hazards else 0,
    }


def _route_option_summary_from_ranked(ranked: dict) -> dict:
    """Same shape as `_route_option_summary`, built from a `RankedRoute
    .model_dump(mode="json")` dict (`OrchestrationState.route_alternatives`'
    own shape, see `OrchestrationNodes.route`)."""
    route = ranked["route"]
    decision = ranked.get("decision") or {}
    safety = ranked.get("safety") or {}
    return {
        "label": ranked["label"],
        "latitude": route["destination"]["latitude"],
        "longitude": route["destination"]["longitude"],
        "distance_km": route["metrics"]["total_distance_km"],
        "total_cost": route["metrics"]["total_cost"],
        "risk_level": ranked.get("risk_level"),
        "risk_score": decision.get("risk_score"),
        "confidence": route.get("confidence"),
        "decision_outcome": decision.get("outcome"),
        "decision_reason": decision.get("reason"),
        "safety_outcome": safety.get("outcome"),
        "safety_reason": safety.get("reason"),
        "hazard_count": len(ranked.get("hazards_near_route") or []),
    }


def _route_option_to_decision_and_safety(option: dict) -> tuple[Decision, SafetyGuardResult]:
    decision = Decision(
        outcome=option["decision_outcome"] or "NO_SAFE_RECOMMENDATION",
        risk_level=option["risk_level"] or "HIGH",
        risk_score=option["risk_score"] if option["risk_score"] is not None else 1.0,
        confidence=option["confidence"] if option["confidence"] is not None else 0.0,
        safety_guard_outcome=option["safety_outcome"] or "BLOCK_MISSING_DATA",
        reason=option["decision_reason"] or "stored route option",
    )
    safety = SafetyGuardResult(
        outcome=option["safety_outcome"] or "BLOCK_MISSING_DATA",
        reason=option["safety_reason"] or "stored route option",
        triggered_rule="stored_conversation_context",
    )
    return decision, safety


def _handle_conversational_followup(
    *, final_state: OrchestrationState, session: SessionState, evidence_agent: EvidenceExplanationAgent,
) -> _FishingQueryResponse | None:
    intent = final_state.intent
    if intent is None or not intent.refers_to_prior:
        return None

    # --- Route: "what about the alternative?" / "what about Route B?" ----
    if intent.selection_reference == "alternative" and session.last_route_options and len(session.last_route_options) > 1:
        option = session.last_route_options[1]
        decision, safety = _route_option_to_decision_and_safety(option)
        provenance = DecisionProvenanceGraph(
            query_id=final_state.query_id,
            route=RouteProvenance(distance_km=option["distance_km"], total_cost=option["total_cost"], feasibility_status="FEASIBLE"),
            safety=safety, decision=decision, generated_at=datetime.now(timezone.utc),
        )
        explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=final_state.persona or "fisherman")
        data = {
            "status": "completed", "language": final_state.language,
            "decision": decision.model_dump(mode="json"), "safety": safety.model_dump(mode="json"),
            "explanation": explanation.rationale, "used_fallback_template": explanation.used_fallback_template,
            "route_note": f"Route {option['label']}: {option['distance_km']:.1f} km, {option['risk_level']} risk, {option['decision_outcome']}.",
            "reused_prior_result": True,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=decision.confidence, provenance=provenance)

    # --- Route: "which is safer?" / "compare them" -------------------------
    if intent.operation == "compare" and session.last_route_options and len(session.last_route_options) > 1 and session.last_route_comparison:
        comparison = session.last_route_comparison
        recommended_label = comparison.get("recommended_label")
        recommended = next((o for o in session.last_route_options if o["label"] == recommended_label), session.last_route_options[0])
        decision, safety = _route_option_to_decision_and_safety(recommended)
        provenance = DecisionProvenanceGraph(
            query_id=final_state.query_id,
            route=RouteProvenance(distance_km=recommended["distance_km"], total_cost=recommended["total_cost"], feasibility_status="FEASIBLE"),
            safety=safety, decision=decision, generated_at=datetime.now(timezone.utc),
        )
        explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=final_state.persona or "fisherman")
        data = {
            "status": "completed", "language": final_state.language,
            "decision": decision.model_dump(mode="json"), "safety": safety.model_dump(mode="json"),
            "explanation": explanation.rationale, "used_fallback_template": explanation.used_fallback_template,
            "route_comparison": comparison, "reused_prior_result": True,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=decision.confidence, provenance=provenance)

    # --- Fishing: "which is safest?" / "compare them" ----------------------
    if intent.operation == "compare" and intent.intent_class == "zone_recommendation" and session.last_fishing_candidates and len(session.last_fishing_candidates) > 1:
        candidates = session.last_fishing_candidates
        eligible = [c for c in candidates if c.get("decision_outcome") in ("RECOMMEND", "RECOMMEND_WITH_CAUTION")]
        pool = eligible or candidates
        best = min(pool, key=lambda c: c.get("risk_score") if c.get("risk_score") is not None else 1.0)
        decision = Decision(
            outcome=best.get("decision_outcome") or "NO_SAFE_RECOMMENDATION", risk_level=best.get("risk_level") or "HIGH",
            risk_score=best.get("risk_score") if best.get("risk_score") is not None else 1.0,
            confidence=best.get("confidence") if best.get("confidence") is not None else 0.0,
            safety_guard_outcome=best.get("safety_outcome") or "BLOCK_MISSING_DATA",
            reason=f"{best['label']} has the lowest risk score among the previously evaluated candidates",
        )
        safety = SafetyGuardResult(
            outcome=best.get("safety_outcome") or "PASS", reason="stored fishing candidate comparison", triggered_rule="stored_conversation_context",
        )
        provenance = DecisionProvenanceGraph(
            query_id=final_state.query_id,
            risk=RiskProvenance(factors=[], score=decision.risk_score, level=decision.risk_level),
            suitability=SuitabilityProvenance(pfz_reference={"status": "unavailable"}, signal_score=1.0 - decision.risk_score, suitability_score=best.get("suitability_score") or 0.0),
            safety=safety, decision=decision, generated_at=datetime.now(timezone.utc),
        )
        explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=final_state.persona or "fisherman")
        data = {
            "status": "completed", "language": final_state.language,
            "decision": decision.model_dump(mode="json"), "safety": safety.model_dump(mode="json"),
            "explanation": explanation.rationale, "used_fallback_template": explanation.used_fallback_template,
            "fishing_candidates": {"top": best, "ranked": candidates, "method": "compared from the previously computed candidate set — no new evaluation"},
            "reused_prior_result": True,
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=decision.confidence, provenance=provenance)

    return None


# --- Phase 7: time-window analysis / best-time (task §8/§9/§10) -----------
#
# Reuses `app.fishing.temporal.evaluate_temporal_suitability` VERBATIM —
# the SAME real multi-hour path `GET /fishing/temporal`/`GET /safety
# /temporal` already expose — never a duplicate temporal engine. Only the
# FRAMING (fishing-suitability-first vs. risk-first) and the best-time
# selection function differ per intent_class.


def _resolve_window_hours(time_window: dict | None) -> int:
    if not isinstance(time_window, dict) or not time_window.get("start") or not time_window.get("end"):
        return 6
    try:
        start = datetime.fromisoformat(str(time_window["start"]))
        end = datetime.fromisoformat(str(time_window["end"]))
    except ValueError:
        return 6
    span_hours = max(1, round((end - start).total_seconds() / 3600))
    return min(24, span_hours)


def _handle_temporal_window_query(
    *, final_state: OrchestrationState, gis_agent: GISGeofencingAgent, evidence_agent: EvidenceExplanationAgent,
) -> _FishingQueryResponse | None:
    intent = final_state.intent
    if intent is None:
        return None

    hours = _resolve_window_hours(intent.time_window)
    risk_config = get_risk_config()
    suitability_weights = get_suitability_weights()

    series = evaluate_temporal_suitability(
        latitude=final_state.latitude, longitude=final_state.longitude, hours=hours, gis_agent=gis_agent,
        risk_config=risk_config, suitability_weights=suitability_weights,
    )

    is_fishing = intent.intent_class == "zone_recommendation"
    best_index = select_best_time_by_suitability(series) if is_fishing else select_best_time_by_risk(series)

    if best_index is None:
        data = {
            "status": "completed", "language": final_state.language,
            "explanation": (
                "None of the real forecast hours in the requested window pass ORCA's deterministic safety checks "
                "right now — this reflects genuinely unfavorable conditions across the whole window, not a system error."
            ),
            "used_fallback_template": True,
            "temporal": {"series": [c.model_dump(mode="json") for c in series], "best_time_index": None, "hours_evaluated": hours},
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    best = series[best_index]
    decision = Decision(
        outcome=best.decision_outcome or "NO_SAFE_RECOMMENDATION", risk_level=best.risk_level or "HIGH",
        risk_score=best.risk_score if best.risk_score is not None else 1.0, confidence=best.confidence or 0.0,
        safety_guard_outcome=best.safety_outcome or "BLOCK_MISSING_DATA",
        reason=f"best available real forecast hour ({best.timestamp.isoformat()}) in the requested window",
    )
    safety = SafetyGuardResult(outcome=best.safety_outcome or "PASS", reason="no blocking condition triggered" if best.safety_outcome == "PASS" else (best.reason or "blocked"), triggered_rule="none")
    provenance = DecisionProvenanceGraph(
        query_id=final_state.query_id,
        risk=RiskProvenance(factors=best.risk_factors, score=best.risk_score or 0.0, level=best.risk_level or "HIGH"),
        suitability=SuitabilityProvenance(pfz_reference={"status": "unavailable"}, signal_score=1.0 - (best.risk_score or 0.0), suitability_score=best.suitability_score or 0.0) if is_fishing else None,
        safety=safety, decision=decision, generated_at=datetime.now(timezone.utc),
    )
    explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=intent.persona or "fisherman")

    data = {
        "status": "completed", "language": final_state.language,
        "decision": decision.model_dump(mode="json"), "safety": safety.model_dump(mode="json"),
        "explanation": explanation.rationale, "used_fallback_template": explanation.used_fallback_template,
        "temporal": {
            "series": [c.model_dump(mode="json") for c in series],
            "best_time_index": best_index,
            "hours_evaluated": hours,
            "ranking": "highest suitability among safe hours" if is_fishing else "lowest risk among safe hours",
            "limitations": [
                "Cyclone hazard presence is evaluated for the CURRENT moment only, not per forecast hour.",
                "Authoritative lightning detection is UNAVAILABLE — each hour's thunderstorm signal is a coarse weather-code proxy, never real detection.",
            ],
        },
    }
    return _FishingQueryResponse(data=data, evidence=None, confidence=decision.confidence, provenance=provenance)


def _handle_zone_recommendation(
    *,
    final_state: OrchestrationState,
    gis_agent: GISGeofencingAgent,
    weather_agent: WeatherIntelligenceAgent,
    oceanographic_agent: OceanographicIntelligenceAgent,
    risk_suitability_agent: RiskSuitabilityAgent,
    evidence_agent: EvidenceExplanationAgent,
    hazard_cache=None,
) -> _FishingQueryResponse | None:
    """Phase 3 — Ask ORCA's fishing-zone-recommendation path.

    Query -> (already ran) query_understanding -> HERE: deterministic
    fishing-intelligence engine (candidate generation -> safety filtering
    -> suitability ranking, app.fishing.engine) -> evidence -> Groq
    (natural-language explanation of the deterministic top candidate,
    app.agents.evidence_explanation.agent.EvidenceExplanationAgent — the
    SAME grounding-checked agent every other query type uses). The LLM
    never invents the recommendation; it explains a result already fully
    decided by generate_candidates/rank_candidates.
    """
    settings = get_settings()
    risk_config = get_risk_config()

    requested_time: datetime | None = None
    time_window = final_state.intent.time_window if final_state.intent else None
    if isinstance(time_window, dict) and time_window.get("start"):
        try:
            requested_time = datetime.fromisoformat(str(time_window["start"]))
        except ValueError:
            requested_time = None

    result = generate_candidates(
        bbox=settings.demo_bbox,
        requested_time=requested_time,
        weather_agent=weather_agent,
        oceanographic_agent=oceanographic_agent,
        gis_agent=gis_agent,
        risk_suitability_agent=risk_suitability_agent,
        risk_config=risk_config,
        hazard_cache=hazard_cache,
    )

    if not result.ranked:
        data = {
            "status": "completed",
            "language": final_state.language,
            "explanation": (
                "ORCA could not find a fishing area that passes its deterministic safety, risk, and suitability "
                "checks in the configured demo region right now. This may reflect genuinely unfavorable conditions "
                "or sparse/insufficient environmental data — not a system error."
            ),
            "used_fallback_template": True,
            "fishing_candidates": {
                "ranked": [], "avoid_count": result.avoid_count, "sample_count": result.sample_count,
                "requested_time": result.requested_time.isoformat(),
            },
        }
        return _FishingQueryResponse(data=data, evidence=None, confidence=None, provenance=None)

    top: FishingCandidate = result.ranked[0]

    decision = Decision(
        outcome=top.decision_outcome, risk_level=top.risk_level, risk_score=top.risk_score,
        confidence=top.confidence or 0.0, safety_guard_outcome=top.safety_outcome, reason=top.reason or "deterministic fishing-zone recommendation",
    )
    safety = SafetyGuardResult(
        outcome=top.safety_outcome, reason="no blocking condition triggered" if top.safety_outcome == "PASS" else (top.reason or "blocked"),
        triggered_rule="none" if top.safety_outcome == "PASS" else "fishing_candidate_filter",
    )
    provenance = DecisionProvenanceGraph(
        query_id=final_state.query_id,
        risk=RiskProvenance(factors=top.risk_factors, score=top.risk_score or 0.0, level=top.risk_level or "HIGH"),
        suitability=SuitabilityProvenance(
            pfz_reference={"status": "unavailable"}, signal_score=1.0 - (top.risk_score or 0.0), suitability_score=top.suitability_score or 0.0,
        ),
        safety=safety,
        decision=decision,
        generated_at=datetime.now(timezone.utc),
    )

    explanation = evidence_agent.explain(provenance=provenance, language=final_state.language, persona=final_state.persona or "fisherman")

    data = {
        "status": "completed",
        "language": final_state.language,
        "decision": decision.model_dump(mode="json"),
        "safety": safety.model_dump(mode="json"),
        "explanation": explanation.rationale,
        "used_fallback_template": explanation.used_fallback_template,
        "fishing_candidates": {
            "top": top.model_dump(mode="json"),
            "ranked": [c.model_dump(mode="json") for c in result.ranked[:5]],
            "ranked_count": result.ranked_count,
            "avoid_count": result.avoid_count,
            "sample_count": result.sample_count,
            "requested_time": result.requested_time.isoformat(),
            "method": result.method,
        },
    }
    return _FishingQueryResponse(data=data, evidence=None, confidence=decision.confidence, provenance=provenance)


class ProvenanceAPIResponse(BaseModel):
    data: dict | None = None
    errors: list[QueryAPIErrorResponse] | None = None


@router.get("/query/{query_id}/provenance")
def get_query_provenance(
    query_id: str,
    response: Response,
    provenance_store: ProvenanceStore = Depends(get_provenance_store),
) -> ProvenanceAPIResponse:
    """architecture.md §34: "Decision Provenance Graph object standalone."
    Retrieves a SPECIFIC past turn's provenance by `query_id`, independent
    of whatever the owning session has moved on to since — never
    reconstructed or guessed if not found.
    """
    provenance = provenance_store.get(query_id)
    if provenance is None:
        response.status_code = 404
        return ProvenanceAPIResponse(
            errors=[QueryAPIErrorResponse(code="PROVENANCE_NOT_FOUND", message=f"no provenance found for query_id {query_id!r}")]
        )
    return ProvenanceAPIResponse(data=provenance.model_dump(mode="json"))
