"""LangGraph node functions — architecture.md §10-§12, §21-§24, §28.

Each node wraps exactly one existing agent/engine (never a new formula,
never a second copy of Phase 2-4 logic — Phase 5 task spec §40) and
returns a partial-update dict, LangGraph's own merge mechanism (confirmed
via smoke test) combines it into the running `OrchestrationState`.

Node-level try/except only ever catches EXPECTED, documented exception
types from the wrapped call (an invalid coordinate, an unusable weather/
marine result) and converts them into a structured `AgentRunRecord` +
`state.errors` entry — never a bare `except Exception`, and never a
silent skip of the Safety Guard: a data node's failure leaves its state
field `None`, which `has_critical_missing_data` downstream is specifically
designed to catch (see `safety_guard` below), not something a node
decides on its own.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.query_understanding.agent import QueryUnderstandingAgent
from app.agents.query_understanding.models import ClarificationNeeded
from app.agents.query_understanding.reference import resolve_reference
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import Settings, get_settings
from app.decision.engine import make_decision, risk_inputs_for_decision
from app.fabric.spatial import InvalidCoordinateError
from app.hazard.engine import detect_all_hazards
from app.i18n.languages import is_supported
from app.orchestration.errors import degraded_run_record, failed_run_record, ok_run_record, skipped_run_record
from app.orchestration.state import OrchestrationState
from app.policy.safety_guard import derive_safety_facts, evaluate_safety_guard
from app.provenance.models import (
    DecisionProvenanceGraph,
    GeographicProvenance,
    RiskProvenance,
    RouteProvenance,
    SuitabilityProvenance,
)
from app.risk.config import RiskConfig, get_risk_config
from app.routing.alternatives import generate_route_alternatives
from app.routing.comparison import compare_routes
from app.routing.config import RoutingConfig, get_routing_config
from app.routing.errors import RoutingError
from app.routing.models import Coordinate, RankedRoute, RouteRequest
from app.routing.safety import evaluate_route_safety
from app.hazard.route_hazards import hazards_near_route
from app.suitability.models import PFZReference

_ROUTE_NOT_AVAILABLE_NOTE = (
    "ORCA cannot compute a route from this conversational query yet: route calculation requires an explicit "
    "origin AND a named/resolvable destination. Say something like \"plan a route from Mangaluru to Udupi\", "
    "or call POST /api/v1/route directly with explicit origin/destination coordinates."
)

_MAX_CONVERSATIONAL_ROUTE_ALTERNATIVES = 2  # bounded — task §31, never "hundreds of routes" even from a chat query


def _bbox_centroid(bbox: dict) -> tuple[float, float]:
    return ((bbox["min_lat"] + bbox["max_lat"]) / 2.0, (bbox["min_lon"] + bbox["max_lon"]) / 2.0)


class OrchestrationNodes:
    """Holds injected agent instances so tests can substitute fast/offline
    fakes (a `FakeLLMProvider`-backed `QueryUnderstandingAgent`, in-memory
    GIS/Weather/Oceanographic agents) without patching module globals.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        risk_config: RiskConfig | None = None,
        query_understanding_agent: QueryUnderstandingAgent | None = None,
        weather_agent: WeatherIntelligenceAgent | None = None,
        oceanographic_agent: OceanographicIntelligenceAgent | None = None,
        gis_agent: GISGeofencingAgent | None = None,
        risk_suitability_agent: RiskSuitabilityAgent | None = None,
        evidence_agent: EvidenceExplanationAgent | None = None,
        hazard_cache=None,
        environmental_provider_class=None,
        routing_config: RoutingConfig | None = None,
    ):
        self._settings = settings or get_settings()
        self._risk_config = risk_config or get_risk_config()
        self._query_understanding_agent = query_understanding_agent or QueryUnderstandingAgent(settings=self._settings)
        self._weather_agent = weather_agent or WeatherIntelligenceAgent(settings=self._settings)
        self._oceanographic_agent = oceanographic_agent or OceanographicIntelligenceAgent(settings=self._settings)
        self._gis_agent = gis_agent or GISGeofencingAgent(settings=self._settings)
        self._risk_suitability_agent = risk_suitability_agent or RiskSuitabilityAgent(
            gis_agent=self._gis_agent, risk_config=self._risk_config
        )
        self._evidence_agent = evidence_agent or EvidenceExplanationAgent(settings=self._settings)
        # Phase 5 (task §28): injectable so tests substitute a fast, offline
        # fake provider (see tests/routing/test_api_route.py's own
        # `FakeEnvironmentalProvider`) — `None` uses the SAME real,
        # bounded-sampling provider `POST /api/v1/route` already uses, so
        # Ask ORCA routing and the direct route endpoint share one real
        # implementation, never two.
        if environmental_provider_class is None:
            from app.agents.environmental_provider import AgentBackedEnvironmentalProvider

            environmental_provider_class = AgentBackedEnvironmentalProvider
        self._environmental_provider_class = environmental_provider_class
        self._routing_config = routing_config
        # Phase 4: injectable so tests substitute an in-memory fake (never a
        # live Redis/GDACS dependency in the fast test suite) — `None`
        # constructs the same best-effort Redis-backed `AgentCache` every
        # other hazard-consuming module already uses (see
        # `app.api.v1.safety.get_hazard_cache`), never crashing the whole
        # request on a cache/network miss.
        self._hazard_cache = hazard_cache if hazard_cache is not None else self._default_hazard_cache()

    @staticmethod
    def _default_hazard_cache():
        from app.agents.common.cache import AgentCache
        from app.services.cache import get_client as get_redis_client

        try:
            client = get_redis_client()
        except Exception:  # noqa: BLE001 — best-effort; a cache miss is never fatal
            client = None
        return AgentCache(client, ttl_seconds=1800)

    # --- Query Understanding -------------------------------------------------

    def query_understanding(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        result = self._query_understanding_agent.understand(query=state.query, now=state.now)

        if isinstance(result, ClarificationNeeded):
            return {
                "clarification": result,
                "status": "clarification_needed",
                "agent_runs": [degraded_run_record("query_understanding", started_at=started, reason=result.reason)],
            }

        # architecture.md §31a: a follow-up's structured reference
        # (refers_to_prior/reference_type/reference_delta) is resolved
        # against the PRIOR turn's already-resolved IntentResult here,
        # deterministically — the LLM above never computed this itself.
        result = resolve_reference(
            result, state.prior_intent, demo_bbox=self._settings.demo_bbox, prior_selected_point=state.prior_selection
        )

        language = result.language if is_supported(result.language) else state.language
        latitude, longitude = _bbox_centroid(result.location["resolved_bbox"])

        # Phase 5 (task §28): the destination centroid, resolved the SAME
        # deterministic way the origin's `latitude`/`longitude` already are
        # — `None` unless `resolve_location` actually resolved a
        # `destination_name` (route_planning naming two places).
        destination_latitude = destination_longitude = None
        if result.destination is not None:
            destination_latitude, destination_longitude = _bbox_centroid(result.destination["resolved_bbox"])

        return {
            "intent": result,
            "language": language,
            "persona": result.persona,
            "latitude": latitude,
            "longitude": longitude,
            "destination_latitude": destination_latitude,
            "destination_longitude": destination_longitude,
            "agent_runs": [ok_run_record("query_understanding", started_at=started)],
        }

    # --- Parallel data-agent branch -----------------------------------------

    def weather(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        try:
            result = self._weather_agent.get_weather(
                latitude=state.latitude, longitude=state.longitude, requested_time=state.now
            )
        except InvalidCoordinateError as exc:
            return {
                "errors": [f"weather: {exc}"],
                "agent_runs": [failed_run_record("weather", started_at=started, error=str(exc))],
            }
        return {
            "weather": result,
            "agent_runs": [
                ok_run_record(
                    "weather", started_at=started, source_tier=result.source_tier, confidence=result.confidence
                )
            ],
        }

    def oceanographic(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        try:
            result = self._oceanographic_agent.get_marine(
                latitude=state.latitude, longitude=state.longitude, requested_time=state.now
            )
        except InvalidCoordinateError as exc:
            return {
                "errors": [f"oceanographic: {exc}"],
                "agent_runs": [failed_run_record("oceanographic", started_at=started, error=str(exc))],
            }
        return {
            "marine": result,
            "agent_runs": [
                ok_run_record(
                    "oceanographic", started_at=started, source_tier=result.source_tier, confidence=result.confidence
                )
            ],
        }

    def gis(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        try:
            geofences, metadata = self._gis_agent.get_geofences()
            boundary_check = self._gis_agent.evaluate_point(state.latitude, state.longitude, geofences=geofences)
            distance_km = self._gis_agent.nearest_hard_geofence_distance_km(
                state.latitude, state.longitude, geofences=geofences
            )
        except InvalidCoordinateError as exc:
            return {
                "errors": [f"gis: {exc}"],
                "agent_runs": [failed_run_record("gis", started_at=started, error=str(exc))],
            }
        return {
            "boundary_check": boundary_check,
            "nearest_hard_geofence_distance_km": distance_km,
            "geofence_disclaimer": metadata.get("disclaimer"),
            "agent_runs": [ok_run_record("gis", started_at=started, source_tier=metadata.get("source_tier"))],
        }

    # --- Risk & Suitability / Safety / Decision -----------------------------

    def risk_suitability(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        if state.weather is None or state.marine is None:
            reason = "weather or oceanographic data unavailable — see state.errors"
            return {
                "risk_suitability": RiskSuitabilityResult(status="insufficient_data", reason=reason),
                "agent_runs": [degraded_run_record("risk_suitability", started_at=started, reason=reason)],
            }

        distance_km = state.nearest_hard_geofence_distance_km if state.nearest_hard_geofence_distance_km is not None else 0.0
        pfz_reference = PFZReference.unavailable()

        result = self._risk_suitability_agent.evaluate(
            weather=state.weather,
            marine=state.marine,
            latitude=state.latitude,
            longitude=state.longitude,
            distance_to_zone_km=distance_km,
            pfz_reference=pfz_reference,
        )

        if result.status == "insufficient_data":
            return {
                "risk_suitability": result,
                "agent_runs": [degraded_run_record("risk_suitability", started_at=started, reason=result.reason or "")],
            }
        return {
            "risk_suitability": result,
            "agent_runs": [ok_run_record("risk_suitability", started_at=started, confidence=result.confidence)],
        }

    def safety_guard(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        facts = derive_safety_facts(
            weather=state.weather,
            marine=state.marine,
            boundary_check=state.boundary_check,
            risk_suitability=state.risk_suitability,
        )

        # Phase 4: real hazard-awareness for EVERY intent that reaches this
        # one shared node (safety_check, route_planning,
        # diagnostic_exploration, boundary_check, zone_recommendation) —
        # never a duplicate intent, never a second Safety Guard. Mirrors
        # `app.api.v1.safety._evaluate_safety`'s exact wiring: `.model_copy`
        # overrides the one previously-always-False fact
        # (`has_active_high_severity_advisory`); `derive_safety_facts`
        # itself is untouched. Skipped only when weather/marine are both
        # unavailable (nothing to detect a weather-based hazard FROM, and a
        # missing-data BLOCK already takes precedence regardless).
        hazards: list = []
        unavailable_sources: list = []
        if state.weather is not None and state.marine is not None and state.latitude is not None and state.longitude is not None:
            hazards, unavailable_sources = detect_all_hazards(
                weather=state.weather, marine=state.marine, latitude=state.latitude, longitude=state.longitude,
                cache=self._hazard_cache,
            )
            critical_hazard_active = any(h.severity in ("DANGER", "CRITICAL") for h in hazards)
            facts = facts.model_copy(update={"has_active_high_severity_advisory": critical_hazard_active})

        result = evaluate_safety_guard(facts, min_confidence_threshold=self._risk_config.safety.min_confidence_threshold)
        return {
            "safety": result,
            "hazards": hazards,
            "hazard_unavailable_sources": unavailable_sources,
            "agent_runs": [ok_run_record("safety_guard", started_at=started)],
        }

    def decision(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        risk_level, risk_score, confidence = risk_inputs_for_decision(state.risk_suitability)

        result = make_decision(
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            min_confidence_threshold=self._risk_config.safety.min_confidence_threshold,
            safety_guard_result=state.safety,
            alternative_exists=False,  # alternative-site search is out of scope this phase (documented limitation)
        )
        return {"decision": result, "agent_runs": [ok_run_record("decision", started_at=started)]}

    # --- Route (conditional) ------------------------------------------------

    def route(self, state: OrchestrationState) -> dict:
        """Phase 5 (task §28): the real "Route Agent" step of the diagram
        `User -> Query Understanding -> LangGraph -> Route Agent ->
        deterministic route generation -> Risk -> Hazards -> Safety ->
        Route ranking -> Evidence -> Groq explanation`. Reuses `app.routing
        .alternatives`/`app.routing.safety`/`app.routing.comparison` —
        EXACTLY the same deterministic engines `POST /api/v1/route` calls —
        never a second implementation. This node ONLY runs when
        `after_decision` already confirmed `intent.requires_route` AND the
        ORIGIN point's own Safety Guard passed (unchanged graph topology,
        see app.orchestration.edges); it falls back to the pre-Phase-5
        honest "cannot route" note whenever no destination could be
        resolved (e.g. the query named only one place, or none).
        """
        started = datetime.now(timezone.utc)

        if state.destination_latitude is None or state.destination_longitude is None:
            return {
                "route_note": _ROUTE_NOT_AVAILABLE_NOTE,
                "agent_runs": [skipped_run_record("route", reason=_ROUTE_NOT_AVAILABLE_NOTE)],
            }

        bbox = self._settings.demo_bbox
        routing_config = self._routing_config or get_routing_config()

        try:
            request = RouteRequest(
                origin=Coordinate(latitude=state.latitude, longitude=state.longitude),
                destination=Coordinate(latitude=state.destination_latitude, longitude=state.destination_longitude),
                requested_time=state.now,
            )
        except ValueError as exc:
            note = f"ORCA could not plan a route between these points: {exc}"
            return {"route_note": note, "agent_runs": [failed_run_record("route", started_at=started, error=str(exc))]}

        geofences, _metadata = self._gis_agent.get_geofences(bbox=bbox)
        provider = self._environmental_provider_class(
            gis_agent=self._gis_agent, requested_time=state.now, risk_config=self._risk_config
        )
        provider.prepare(bbox)

        try:
            routes = generate_route_alternatives(
                request,
                bbox=bbox,
                geofences=geofences,
                risk_provider=provider.risk_provider,
                hazard_provider=provider.hazard_provider,
                temporal_validity=provider.overall_temporal_validity,
                confidence=provider.overall_confidence,
                mode=self._settings.orca_mode,
                data_quality="fixture" if provider.used_synthetic_fallback else "live",
                routing_config=routing_config,
                risk_config=self._risk_config,
                max_alternatives=_MAX_CONVERSATIONAL_ROUTE_ALTERNATIVES,
            )
        except RoutingError as exc:
            note = f"ORCA could not compute a route for this query: {exc}"
            return {"route_note": note, "agent_runs": [failed_run_record("route", started_at=started, error=str(exc))]}

        ranked_routes: list[RankedRoute] = []
        for index, one_route in enumerate(routes):
            label = chr(ord("A") + index)
            hazards, hazard_tier = hazards_near_route(one_route.path_coordinates, cache=self._hazard_cache)
            decision, safety, risk_level = evaluate_route_safety(
                one_route, hazards_near_route=hazards, risk_config=self._risk_config, alternative_exists=len(routes) > 1
            )
            ranked_routes.append(
                RankedRoute(
                    label=label, route=one_route, risk_level=risk_level, decision=decision, safety=safety,
                    hazards_near_route=hazards, hazard_source_tier=hazard_tier,
                )
            )

        comparison = compare_routes(ranked_routes) if len(ranked_routes) > 1 else None
        primary = ranked_routes[0]

        note = (
            f"Route {primary.label}: {primary.route.metrics.total_distance_km:.1f} km, "
            f"{primary.risk_level} risk, {primary.decision.outcome}."
        )
        if comparison is not None:
            note += f" {comparison.reason}"

        return {
            # The route's OWN decision/safety become the query's decision/
            # safety for a route_planning query — the origin-point-only
            # values computed earlier by `decision()` are superseded here,
            # never blended: `DecisionProvenanceGraph.decision`/`.route`
            # were already designed to carry exactly one "the answer for
            # this query" Decision plus a RouteProvenance sibling (see
            # `_build_provenance` below). Every OTHER intent never reaches
            # this node, so its own point-based decision/safety are
            # completely unaffected.
            "route": primary.route,
            "decision": primary.decision,
            "safety": primary.safety,
            "route_note": note,
            "route_hazards": primary.hazards_near_route,
            "route_alternatives": [r.model_dump(mode="json") for r in ranked_routes[1:]],
            "route_comparison": comparison.model_dump(mode="json") if comparison is not None else None,
            "agent_runs": [ok_run_record("route", started_at=started, confidence=primary.route.confidence)],
        }

    # --- Evidence & Explanation ------------------------------------------------

    def evidence(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        provenance = _build_provenance(state)
        result = self._evidence_agent.explain(
            provenance=provenance, language=state.language, persona=state.persona or "fisherman"
        )
        return {
            "provenance": provenance,
            "explanation": result,
            "status": "completed",
            "agent_runs": [ok_run_record("evidence_explanation", started_at=started)],
        }


def _build_provenance(state: OrchestrationState) -> DecisionProvenanceGraph:
    risk_provenance = None
    suitability_provenance = None
    if state.risk_suitability is not None and state.risk_suitability.status == "ok":
        rr = state.risk_suitability.risk_result
        risk_provenance = RiskProvenance(factors=rr.factors, score=rr.score, level=rr.level)
        sr = state.risk_suitability.suitability_result
        if sr is not None:
            suitability_provenance = SuitabilityProvenance(
                pfz_reference=sr.pfz_reference, signal_score=sr.components.signal, suitability_score=sr.score
            )

    geographic_provenance = GeographicProvenance(
        boundary_check=state.boundary_check, restricted_zone_check=None, illustrative_layer_disclosure=state.geofence_disclaimer
    )

    route_provenance = None
    if state.route is not None:
        route_provenance = RouteProvenance(
            distance_km=state.route.metrics.total_distance_km,
            total_cost=state.route.metrics.total_cost,
            feasibility_status=state.route.feasibility_status,
            avoided_hazard_cells=0,
        )
        # Phase 5: the ROUTE's own risk (its max per-cell score/level,
        # already carried on `state.decision` — see `OrchestrationNodes
        # .route`, which overrides `decision` with the route-level Decision)
        # replaces the ORIGIN point's `RiskProvenance` for a route_planning
        # query. Without this override, the Evidence & Explanation Agent
        # would ground its explanation in the wrong number — the origin
        # point's own standalone risk score, not the risk of the route it
        # is actually describing (task's own "never let Groq invent/misstate
        # the evidence" requirement). `factors=[]`: the route's risk is an
        # aggregate (worst per-cell score along the path), not a single
        # itemized Risk Engine factor breakdown — an honest empty list, not
        # a fabricated reuse of the origin point's unrelated factors.
        if state.decision is not None:
            risk_provenance = RiskProvenance(factors=[], score=state.decision.risk_score, level=state.decision.risk_level)
        # Fishing suitability at the ORIGIN point has no bearing on "is this
        # route safe" — suppressed here so the Evidence Agent's explanation
        # stays on-topic rather than mixing in an unrelated fishing score.
        suitability_provenance = None

    return DecisionProvenanceGraph(
        query_id=state.query_id,
        risk=risk_provenance,
        suitability=suitability_provenance,
        geographic=geographic_provenance,
        conflicts=[],  # architecture.md §12/§20: only one source per domain exists — honestly always empty
        safety=state.safety,
        route=route_provenance,
        decision=state.decision,
        generated_at=datetime.now(timezone.utc),
    )
