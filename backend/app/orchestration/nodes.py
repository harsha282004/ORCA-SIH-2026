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
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import Settings, get_settings
from app.decision.engine import make_decision
from app.fabric.spatial import InvalidCoordinateError
from app.i18n.languages import is_supported
from app.orchestration.errors import degraded_run_record, failed_run_record, ok_run_record, skipped_run_record
from app.orchestration.state import OrchestrationState
from app.policy.models import SafetyFacts
from app.policy.safety_guard import evaluate_safety_guard
from app.provenance.models import (
    DecisionProvenanceGraph,
    GeographicProvenance,
    RiskProvenance,
    RouteProvenance,
    SuitabilityProvenance,
)
from app.risk.config import RiskConfig, get_risk_config
from app.suitability.models import PFZReference

_ROUTE_NOT_AVAILABLE_NOTE = (
    "ORCA cannot compute a route from this conversational query yet: route calculation requires an explicit "
    "origin AND destination coordinate pair (architecture.md §26's RouteRequest contract), and the Query "
    "Understanding Agent only resolves a single target location this phase — it never invents a second "
    "(origin) coordinate. Call POST /api/v1/route directly with explicit origin/destination coordinates to "
    "compute a route."
)


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

        language = result.language if is_supported(result.language) else state.language
        latitude, longitude = _bbox_centroid(result.location["resolved_bbox"])

        return {
            "intent": result,
            "language": language,
            "persona": result.persona,
            "latitude": latitude,
            "longitude": longitude,
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

        has_boundary_violation = bool(state.boundary_check and state.boundary_check.blocked)
        has_critical_missing_data = (
            state.weather is None
            or state.marine is None
            or state.boundary_check is None
            or state.risk_suitability is None
            or state.risk_suitability.status == "insufficient_data"
        )
        confidence = state.risk_suitability.confidence if state.risk_suitability and state.risk_suitability.status == "ok" else 0.0
        # architecture.md §29: no official advisory ingestion exists yet
        # (Phase 1-5 never acquired one) — always False, an honest,
        # documented scope limitation, never a fabricated "no hazard" claim
        # about a data source that was never actually checked.
        has_active_high_severity_advisory = False

        facts = SafetyFacts(
            has_boundary_violation=has_boundary_violation,
            has_critical_missing_data=has_critical_missing_data,
            confidence=confidence,
            has_active_high_severity_advisory=has_active_high_severity_advisory,
        )
        result = evaluate_safety_guard(facts, min_confidence_threshold=self._risk_config.safety.min_confidence_threshold)
        return {"safety": result, "agent_runs": [ok_run_record("safety_guard", started_at=started)]}

    def decision(self, state: OrchestrationState) -> dict:
        started = datetime.now(timezone.utc)
        if state.risk_suitability is not None and state.risk_suitability.status == "ok":
            risk_level = state.risk_suitability.risk_result.level
            risk_score = state.risk_suitability.risk_result.score
            confidence = state.risk_suitability.confidence
        else:
            # Conservative placeholders — never actually determinative,
            # since `state.safety.outcome` will already be a BLOCK_* (the
            # Safety Guard's `has_critical_missing_data` check above always
            # fires whenever risk_suitability isn't "ok"), and
            # `make_decision` maps any non-PASS safety outcome to
            # NO_SAFE_RECOMMENDATION regardless of these values.
            risk_level = "HIGH"
            risk_score = 1.0
            confidence = 0.0

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
        return {
            "route_note": _ROUTE_NOT_AVAILABLE_NOTE,
            "agent_runs": [skipped_run_record("route", reason=_ROUTE_NOT_AVAILABLE_NOTE)],
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
