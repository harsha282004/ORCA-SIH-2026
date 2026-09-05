"""Fishing Suitability Engine data contracts — architecture.md §21.

CRITICAL — architecture.md §21's "hard discipline rule": official INCOIS
PFZ remains official PFZ, always cited with its own timestamp and source
tier; ORCA's own ranking is always rendered under a visually distinct
"ORCA Fishing Suitability" label, never merged into or presented as an
official forecast. `PFZReference` is therefore informational/citation
only — its value is never blended into `SuitabilityResult.score`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PFZStatus = Literal["unavailable", "available"]


class PFZReference(BaseModel):
    """architecture.md §17 (Phase 1 task): "If PFZ information is
    unavailable: represent it as unavailable. Do not invent PFZ locations."
    Phase 1 did not acquire a real INCOIS PFZ snapshot, so every
    PFZReference constructed in this codebase today has status="unavailable".
    """

    status: PFZStatus
    value: str | None = None  # e.g. "favorable" / "unfavorable" — only meaningful if status == "available"
    source: str | None = None
    observed_at: datetime | None = None

    @classmethod
    def unavailable(cls) -> "PFZReference":
        return cls(status="unavailable")


class SuitabilityComponents(BaseModel):
    signal: float
    safety: float
    distance: float
    data_confidence: float


class SuitabilityResult(BaseModel):
    label: Literal["ORCA Fishing Suitability"] = "ORCA Fishing Suitability"
    score: float
    components: SuitabilityComponents
    pfz_reference: PFZReference
    disclaimer: str = (
        "ORCA Fishing Suitability is an independent, ORCA-derived calculation. "
        "It is not the official PFZ (Potential Fishing Zone) advisory, does not "
        "override it, and is never presented as an official government forecast."
    )
