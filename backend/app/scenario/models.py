"""Scenario Engine data contracts — architecture.md §32.

"MVP-lite: shares its implementation with multi-turn state — a scenario is
simply a perturbed re-entry into the same deterministic re-scoring path."
These contracts wrap the SAME `RiskSuitabilityResult`/`SafetyGuardResult`/
`Decision` shapes the live pipeline already produces — no second output
schema for "simulated" results.
"""
from __future__ import annotations

from pydantic import BaseModel, model_validator

from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.decision.models import Decision
from app.policy.models import SafetyGuardResult


class ScenarioPerturbation(BaseModel):
    """architecture.md §32's own worked example is "wave_height + 1m";
    `wind_speed_delta_ms` extends this to the one other Risk Engine input
    (`app.risk.components.wind_risk`) that is perturbable the same way —
    never a new risk factor, only a delta on two that already exist. At
    least one field must be set; a scenario with no perturbation at all is
    not a scenario.
    """

    wave_height_delta_m: float | None = None
    wind_speed_delta_ms: float | None = None

    @model_validator(mode="after")
    def _at_least_one_delta(self) -> "ScenarioPerturbation":
        if self.wave_height_delta_m is None and self.wind_speed_delta_ms is None:
            raise ValueError("at least one of wave_height_delta_m/wind_speed_delta_ms must be set")
        return self


class ScenarioSnapshot(BaseModel):
    """One side of a scenario diff (baseline or perturbed)."""

    risk_suitability: RiskSuitabilityResult
    safety: SafetyGuardResult
    decision: Decision


class ScenarioResult(BaseModel):
    # architecture.md §32: "UI must render 'SIMULATION — NOT LIVE DATA'
    # wherever a scenario result is shown" — carried on the payload itself
    # so no consumer can accidentally drop the label.
    label: str = "SIMULATION — NOT LIVE DATA"
    perturbation: ScenarioPerturbation
    baseline: ScenarioSnapshot
    scenario: ScenarioSnapshot
    risk_score_delta: float
    decision_changed: bool
    safety_outcome_changed: bool
