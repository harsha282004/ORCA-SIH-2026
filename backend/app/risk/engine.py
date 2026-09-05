"""The deterministic ORCA Risk Engine — architecture.md §22.

Operates on already-normalized [0, 1] component values (see
app.risk.components for the raw-value-to-normalized functions) so that the
weighted-sum formula itself can be tested against architecture.md §22's
exact worked example independent of any particular normalization curve:

    wave=0.55, wind=0.40, advisory=0.0, lightning=0.0,
    restricted_zone_distance=0.30, coast_distance=0.10, data_confidence_penalty=0.0
    -> 0.1375 + 0.060 + 0.0 + 0.0 + 0.045 + 0.010 + 0.0 = 0.2525 -> LOW

The LLM never determines risk — this module has no LLM dependency and
never will; it is pure arithmetic over validated inputs.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.risk.config import RiskThresholds, RiskWeights

RiskLevel = Literal["LOW", "MODERATE", "HIGH"]

_COMPONENT_NAMES = (
    "wave",
    "wind",
    "advisory_or_hazard_flag",
    "lightning_thunderstorm_proxy",
    "restricted_zone_distance",
    "coast_distance",
    "data_confidence_penalty",
)


class MissingRiskComponentError(ValueError):
    """Raised when one or more required risk components are missing.
    Missing data must never silently become zero risk (Phase 2 spec) — the
    caller must supply every component explicitly, or route to the Safety
    Guard's BLOCK_MISSING_DATA instead of calling compute_risk at all.
    """


class NormalizedRiskComponents(BaseModel):
    """Every field is the already-normalized [0, 1] value for that named
    architecture.md §22 factor. `None` means "not available" — it is never
    treated as 0.0.
    """

    wave: float | None = Field(default=None, ge=0.0, le=1.0)
    wind: float | None = Field(default=None, ge=0.0, le=1.0)
    advisory_or_hazard_flag: float | None = Field(default=None, ge=0.0, le=1.0)
    lightning_thunderstorm_proxy: float | None = Field(default=None, ge=0.0, le=1.0)
    restricted_zone_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    coast_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    data_confidence_penalty: float | None = Field(default=None, ge=0.0, le=1.0)

    def missing_fields(self) -> list[str]:
        dumped = self.model_dump()
        return [name for name in _COMPONENT_NAMES if dumped[name] is None]


class RiskFactor(BaseModel):
    name: str
    normalized_value: float
    weight: float
    contribution: float


class RiskResult(BaseModel):
    score: float
    level: RiskLevel
    factors: list[RiskFactor]


def classify_risk_level(score: float, thresholds: RiskThresholds) -> RiskLevel:
    if score < thresholds.low_max:
        return "LOW"
    if score < thresholds.moderate_max:
        return "MODERATE"
    return "HIGH"


def compute_risk(
    components: NormalizedRiskComponents,
    weights: RiskWeights,
    thresholds: RiskThresholds,
) -> RiskResult:
    missing = components.missing_fields()
    if missing:
        raise MissingRiskComponentError(f"missing required risk components: {missing}")

    weight_map = weights.model_dump()
    component_map = components.model_dump()

    factors: list[RiskFactor] = []
    total = 0.0
    for name in _COMPONENT_NAMES:
        normalized_value = component_map[name]
        weight = weight_map[name]
        contribution = normalized_value * weight
        total += contribution
        factors.append(RiskFactor(name=name, normalized_value=normalized_value, weight=weight, contribution=contribution))

    # Mathematically already in [0, 1] (each factor in [0,1], weights sum to
    # 1.0) — clamped only to absorb floating-point drift, never to hide a
    # logic error.
    total = max(0.0, min(1.0, total))

    return RiskResult(score=total, level=classify_risk_level(total, thresholds), factors=factors)
