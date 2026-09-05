"""Decision Engine data contracts — architecture.md §24."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.policy.models import SafetyGuardOutcome
from app.risk.engine import RiskLevel

DecisionOutcome = Literal["RECOMMEND", "RECOMMEND_WITH_CAUTION", "PROVIDE_ALTERNATIVES", "NO_SAFE_RECOMMENDATION"]


class Decision(BaseModel):
    """A structured decision object — no natural-language explanation is
    generated here (that is the Evidence & Explanation Agent's job,
    Phase 4+, architecture.md §28). The LLM never chooses this outcome.
    """

    outcome: DecisionOutcome
    risk_level: RiskLevel
    risk_score: float
    confidence: float
    safety_guard_outcome: SafetyGuardOutcome
    reason: str
    alternative_used: bool = False
