"""LangGraph orchestration state — architecture.md §10-§12, §27-§28, §31,
Phase 5 task spec §16.

A typed Pydantic model, not a raw dict (Phase 5 task spec §16): every field
a node reads or writes is declared here, so a node that forgets to set a
field is a visible `None`, never a silent `KeyError` or an untyped blob.

Fields written by more than one node running in the SAME parallel step
(`agent_runs`, `errors`) use `Annotated[..., operator.add]` so LangGraph
merges each branch's contribution instead of raising
`InvalidUpdateError: Can receive only one value per step` — confirmed via
a live smoke test against the installed langgraph package. Every other
field is written by exactly one node (or overwritten later in the same
linear path), so a plain field is correct and simpler.
"""
from __future__ import annotations

import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.agents.evidence_explanation.models import ExplanationResult
from app.agents.query_understanding.models import ClarificationNeeded, IntentResult
from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.decision.models import Decision
from app.gis.geofence import GeofenceCheckResult
from app.i18n.languages import DEFAULT_LANGUAGE
from app.models.contracts import AgentResult
from app.policy.models import SafetyGuardResult
from app.provenance.models import AgentRunRecord, DecisionProvenanceGraph
from app.routing.models import RouteResult

OrchestrationStatus = Literal["in_progress", "clarification_needed", "completed", "failed"]


class OrchestrationState(BaseModel):
    # --- Input -------------------------------------------------------------
    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    session_id: str | None = None
    now: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Query Understanding -------------------------------------------------
    language: str = DEFAULT_LANGUAGE
    persona: str | None = None
    intent: IntentResult | None = None
    clarification: ClarificationNeeded | None = None
    latitude: float | None = None
    longitude: float | None = None

    # --- Parallel data-agent branch (Weather / Oceanographic / GIS) --------
    weather: AgentResult | None = None
    marine: AgentResult | None = None
    boundary_check: GeofenceCheckResult | None = None
    nearest_hard_geofence_distance_km: float | None = None
    geofence_disclaimer: str | None = None

    # --- Risk & Suitability / Safety / Decision -----------------------------
    risk_suitability: RiskSuitabilityResult | None = None
    safety: SafetyGuardResult | None = None
    decision: Decision | None = None

    # --- Route (conditional) ------------------------------------------------
    route: RouteResult | None = None
    route_note: str | None = None

    # --- Evidence & Explanation ----------------------------------------------
    provenance: DecisionProvenanceGraph | None = None
    explanation: ExplanationResult | None = None

    # --- Cross-cutting -------------------------------------------------------
    agent_runs: Annotated[list[AgentRunRecord], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
    status: OrchestrationStatus = "in_progress"
