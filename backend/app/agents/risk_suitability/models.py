"""Risk & Suitability Agent output — architecture.md §10, §22.

Not a new contract competing with Phase 2's own `RiskResult`/
`SuitabilityResult` — this simply bundles them together with the
orchestration-relevant status, since the agent's whole job is to be a thin
wrapper, not a new data model.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.risk.engine import RiskResult
from app.suitability.models import SuitabilityResult

RiskSuitabilityStatus = Literal["ok", "insufficient_data"]


class RiskSuitabilityResult(BaseModel):
    status: RiskSuitabilityStatus
    risk_result: RiskResult | None = None
    confidence: float = 0.0
    suitability_result: SuitabilityResult | None = None
    reason: str | None = None
