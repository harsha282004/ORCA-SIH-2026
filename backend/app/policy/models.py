"""Policy & Safety Guard data contracts — architecture.md §12 (verbatim
``SafetyGuardResult`` shape) and §23.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SafetyGuardOutcome = Literal["PASS", "BLOCK_BOUNDARY", "BLOCK_MISSING_DATA", "BLOCK_LOW_CONFIDENCE", "BLOCK_HAZARD"]


class SafetyGuardResult(BaseModel):
    """Verbatim contract from architecture.md §12."""

    outcome: SafetyGuardOutcome
    reason: str
    triggered_rule: str


class SafetyFacts(BaseModel):
    """The deterministic facts the Safety Guard evaluates — architecture.md
    §23's `evidence_bundle`/`risk_result` inputs, flattened into an
    explicit, directly-unit-testable input contract. Every field must be
    supplied; there is no "unknown" default for a safety-relevant fact.
    """

    has_boundary_violation: bool = Field(
        description="True if the point/route falls inside a HARD geofence (land, protected area, "
        "international boundary, or an active restricted zone) — app.gis.geofence's result."
    )
    has_critical_missing_data: bool = Field(
        description="True if a factor the current intent requires (e.g. wave/wind for a safety_check) "
        "could not be resolved at all — never inferred from a merely-stale value."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    has_active_high_severity_advisory: bool = Field(
        description='architecture.md §23: evidence_bundle.has_active_official_advisory_at("HIGH")'
    )
