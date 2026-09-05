"""Decision Provenance Graph — architecture.md §27, verbatim structure:

    RECOMMENDATION
      +-- Risk calculation      -- Wave/Wind/Advisory/Lightning-proxy evidence
      +-- Fishing suitability   -- PFZ reference / SST / Chlorophyll (where available)
      +-- Geographic validation -- Boundary check / Restricted-zone check / Illustrative-layer disclosure
      +-- Conflict resolution   -- Any ConflictObject(s) and their precedence rule
      +-- Safety guard          -- Outcome + triggered rule
      +-- Route (if requested)  -- Distance / Risk cost / Avoided hazards

"This same object is rendered identically by the chat explanation, the
Evidence Panel, and the Provenance view — one source of truth" (§27). The
Evidence & Explanation Agent (Phase 5) is grounded in exactly this object
and nothing else — it cannot add facts not present here (§28).

architecture.md §37 (Phase 5 task spec §37) also asks for per-node
execution tracing (`AgentRunRecord`) — a lighter-weight companion to the
Decision Provenance Graph, not a second competing provenance system: the
Decision Provenance Graph is the *substantive* trace ("why did ORCA say
this"), `AgentRunRecord` is the *operational* trace ("which nodes ran, in
what order, with what status").
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.decision.models import Decision
from app.gis.geofence import GeofenceCheckResult
from app.models.contracts import ConflictObject
from app.policy.models import SafetyGuardResult
from app.risk.engine import RiskFactor
from app.suitability.models import PFZReference


class RiskProvenance(BaseModel):
    factors: list[RiskFactor]
    score: float
    level: str


class SuitabilityProvenance(BaseModel):
    label: Literal["ORCA Fishing Suitability"] = "ORCA Fishing Suitability"
    pfz_reference: PFZReference
    signal_score: float
    suitability_score: float


class GeographicProvenance(BaseModel):
    boundary_check: GeofenceCheckResult | None = None
    restricted_zone_check: GeofenceCheckResult | None = None
    illustrative_layer_disclosure: str | None = None


class RouteProvenance(BaseModel):
    distance_km: float
    total_cost: float
    feasibility_status: str
    avoided_hazard_cells: int = 0


class DecisionProvenanceGraph(BaseModel):
    query_id: str
    risk: RiskProvenance | None = None
    suitability: SuitabilityProvenance | None = None
    geographic: GeographicProvenance | None = None
    conflicts: list[ConflictObject] = Field(default_factory=list)
    safety: SafetyGuardResult | None = None
    route: RouteProvenance | None = None
    decision: Decision | None = None
    generated_at: datetime


class AgentRunRecord(BaseModel):
    """Operational trace for one graph node — Phase 5 task spec §37."""

    agent_name: str
    status: Literal["ok", "degraded", "failed", "skipped"]
    started_at: datetime
    finished_at: datetime | None = None
    source_tier: str | None = None
    confidence: float | None = None
    errors: list[str] = Field(default_factory=list)
