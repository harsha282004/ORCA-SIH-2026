"""Marine Safety & Hazard Intelligence data contracts — Phase 4.

Deliberately minimal, reusing existing models wherever possible (task
instruction: "do not duplicate existing provenance/freshness models").
`Hazard` is the one genuinely new concept this phase needs — nothing
existing represents "a real-world hazard event with a type, severity,
location, and validity window." Everything else (freshness, confidence,
safety outcome, decision) is the EXISTING `app.policy`/`app.decision`/
`app.models.contracts` machinery, imported and reused, not recreated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.decision.models import DecisionOutcome
from app.policy.models import SafetyGuardOutcome

HazardType = Literal["CYCLONE", "HIGH_WIND", "HIGH_WAVES", "THUNDERSTORM_PROXY", "GEOFENCE_BOUNDARY"]

# Task §13: existing project vocabularies (RiskLevel: LOW/MODERATE/HIGH;
# SafetyGuardOutcome: PASS/BLOCK_*) don't cover "how severe is this
# specific hazard event" — this is the one genuinely new vocabulary Phase 4
# introduces, taken directly from the task's own suggested scale, not
# invented independently.
HazardSeverity = Literal["INFO", "ADVISORY", "WARNING", "DANGER", "CRITICAL"]

# Task §16: the map's overall marine-safety status. Deliberately distinct
# from DecisionOutcome/RiskLevel (neither is a "is it currently safe to be
# on the water" label) but DERIVED from them (see
# app.hazard.safety_status.classify_safety_status) — never a competing
# authority, never computed independently of the existing Decision Engine.
MarineSafetyLevel = Literal["SAFE", "CAUTION", "WARNING", "DANGER", "UNKNOWN"]


class Hazard(BaseModel):
    hazard_type: HazardType
    severity: HazardSeverity
    title: str
    description: str

    latitude: float | None = None  # None for hazards with no single point (e.g. a region-wide wind classification)
    longitude: float | None = None
    distance_km: float | None = None  # from the query location, when relevant (e.g. cyclone proximity)

    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None

    source: str
    is_authoritative: bool
    is_proxy: bool = False  # True for e.g. the WMO-weathercode lightning/thunderstorm proxy — never real detection
    freshness: Literal["CURRENT", "FORECAST", "STALE", "UNKNOWN"] = "UNKNOWN"
    confidence: float | None = None


class HazardSourceStatus(BaseModel):
    """One row of the hazard-source audit (docs/PHASE_4_..._REPORT.md §3),
    also served live via the API so the frontend's "Data Availability"
    panel reads real status, never a hardcoded UI list.
    """

    hazard_type: HazardType
    source: str
    is_authoritative: bool
    programmatically_accessible: bool
    status: Literal["AVAILABLE", "LIMITED", "UNAVAILABLE"]
    reason: str


class MarineSafetyStatus(BaseModel):
    level: MarineSafetyLevel
    reason: str
    decision_outcome: DecisionOutcome | None
    safety_guard_outcome: SafetyGuardOutcome | None
    risk_level: str | None
    risk_score: float | None
    confidence: float | None
    hazards: list[Hazard]
    unavailable_sources: list[HazardSourceStatus]
    generated_at: datetime
