"""Multi-turn session state — architecture.md §31.

Deliberately narrow: this remembers *conversational* context only (the
prior turn's understood intent, the decision that was made, and its
provenance/language) so a follow-up like "what about tomorrow?" can be
resolved relative to something. It never caches environmental
observations as still-current — every new turn re-runs the Weather/
Oceanographic agents (and therefore the Temporal Validity Gate) fresh,
regardless of what is stored here (Phase 5 task spec §24/§31).

The one deliberate exception is `last_weather_snapshot`/
`last_marine_snapshot` (architecture.md §32's Scenario Engine) — see
those fields' own docstring for why a snapshot used only as a labeled
simulation baseline does not conflict with the anti-staleness rule above.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.agents.query_understanding.models import IntentResult
from app.decision.models import Decision
from app.i18n.languages import DEFAULT_LANGUAGE
from app.models.contracts import AgentResult
from app.provenance.models import DecisionProvenanceGraph


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    turn_count: int = 0

    last_query: str | None = None
    last_language: str = DEFAULT_LANGUAGE
    last_intent: IntentResult | None = None
    last_decision: Decision | None = None
    last_provenance: DecisionProvenanceGraph | None = None

    # Phase 6 (task §12/§13/§14/§17/§18) — compact, deterministic
    # conversational context for follow-ups that name/imply a SPECIFIC
    # previously-returned item ("what about the waves there?", "what about
    # the alternative route?", "which is safer?"). Deliberately NOT the
    # full candidate/route objects — only what a follow-up actually needs
    # to re-anchor to (task §14: "do not store excessive conversation
    # history"): a resolved point (so the SAME single-point pipeline can
    # re-run FRESH, never a cached numeric answer — task §15/§18) plus the
    # already-computed comparison summaries for a genuine "compare" reuse
    # (task §17's "reuse previous structured route results where valid").
    last_selected_point: dict | None = None  # {latitude, longitude, label, source: "fishing"|"route"|"safety_check"}
    last_fishing_candidates: list[dict] | None = None  # top few ranked FishingCandidate summaries (label, lat/lon, risk/suitability/decision)
    last_route_options: list[dict] | None = None  # {label, latitude, longitude, distance_km, risk_level, decision_outcome} per route/alternative
    last_route_comparison: dict | None = None  # the RouteComparisonResult already computed for the last route_planning turn

    # architecture.md §32: "Scenario Engine ... shares its implementation
    # with multi-turn state — a scenario is simply a perturbed re-entry
    # into the same deterministic re-scoring path." These two fields exist
    # SOLELY to give the Scenario Engine a baseline to perturb — unlike
    # every other field above, they are never treated as still-current
    # environmental truth: a new real query always re-runs the Weather/
    # Oceanographic agents fresh regardless of what is cached here (see
    # module docstring), and a scenario result built from them is always
    # rendered labeled "SIMULATION — NOT LIVE DATA", never as a live answer.
    last_weather_snapshot: AgentResult | None = None
    last_marine_snapshot: AgentResult | None = None
