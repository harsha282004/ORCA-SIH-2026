"""Fishing Intelligence data contracts — Phase 3.

Deliberately minimal (task instruction: "if a new model is required, keep
it minimal... first inspect whether existing AgentResult/suitability/
provenance models can represent these already"). `FishingCandidate` is a
thin wrapper AROUND the existing `RiskSuitabilityResult`/`Decision`/
`SafetyGuardResult` — it adds only what those don't already carry (a
location, a rank, a distance, a human-readable reason for exclusion). No
new score, no new formula, no new category enum beyond
`app.suitability.engine.classify_suitability_category` (already Phase 2).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.decision.models import DecisionOutcome
from app.policy.models import SafetyGuardOutcome
from app.risk.engine import RiskLevel
from app.suitability.engine import SuitabilityCategory

CandidateStatus = Literal["ranked", "avoid", "insufficient_data"]


class EnvironmentalContext(BaseModel):
    """Real values AT the candidate's exact coordinate, from the same
    Open-Meteo sample already fetched for it. Informational only — SST is
    NOT currently a Suitability Engine input (see `suitability_factors`
    below for what actually IS); shown here so a user/LLM can see real
    conditions without mistaking them for suitability-score drivers.
    """

    sea_surface_temperature_c: float | None = None
    wave_height_m: float | None = None
    wave_direction_deg: float | None = None
    wind_speed_ms: float | None = None
    ocean_current_velocity_ms: float | None = None


class FishingCandidate(BaseModel):
    latitude: float
    longitude: float

    status: CandidateStatus
    reason: str | None = None  # populated for "avoid"/"insufficient_data" — why this candidate was excluded

    # --- Deterministic Suitability Engine output (app.suitability.engine,
    # via app.agents.risk_suitability.agent.RiskSuitabilityAgent — the
    # EXACT same call every other ORCA surface uses) ---
    suitability_score: float | None = None
    suitability_category: SuitabilityCategory | None = None
    # The engine's own documented limitation (see app.agents.risk_suitability
    # .agent's module docstring): signal_score is `1 - risk_score` — a
    # wave/wind-based proxy. Neither chlorophyll nor bathymetry nor INCOIS
    # SST feed into this score today. Never claim otherwise.
    suitability_signal_is_risk_proxy: bool = True

    # --- Deterministic Risk Engine output — the REAL contributing factors ---
    risk_score: float | None = None
    risk_level: RiskLevel | None = None
    risk_factors: list[dict] = []  # RiskFactor.model_dump() each — name/normalized_value/weight/contribution, verbatim

    # --- Safety Guard + Decision Engine (safety precedence, enforced) ---
    safety_outcome: SafetyGuardOutcome | None = None
    decision_outcome: DecisionOutcome | None = None
    is_authoritative_restricted: bool | None = None  # boundary_check.blocked, when a hard geofence applies

    confidence: float | None = None
    environmental_context: EnvironmentalContext | None = None

    # --- Phase 4: real detected hazards considered for this candidate
    # (app.hazard.engine.Hazard.model_dump() each). Empty when hazard
    # detection was not requested (default, backward-compatible with
    # Phase 3 callers) OR when it was requested and genuinely found none —
    # `active_hazards_checked` disambiguates the two so a UI never confuses
    # "not evaluated" with "evaluated, clear."
    active_hazards: list[dict] = []
    active_hazards_checked: bool = False

    distance_km: float | None = None  # from a reference point, only populated by nearest/comparison queries
    rank: int | None = None  # 1-based, only populated once ranked

    source: str = "ORCA deterministic Risk & Suitability Agent (app.agents.risk_suitability.agent)"
    timestamp: datetime


class FishingCandidateSet(BaseModel):
    ranked: list[FishingCandidate]
    avoid: list[FishingCandidate]
    sample_count: int
    ranked_count: int
    avoid_count: int
    requested_time: datetime
    generated_at: datetime
    method: str


class AreaComparisonResult(BaseModel):
    candidates: list[FishingCandidate]
    better_candidate_index: int | None  # index into `candidates` — None if neither is safely rankable
    reason: str
    generated_at: datetime
