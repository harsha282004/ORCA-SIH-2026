"""Confidence calculation — architecture.md §22.

    confidence = 0.40 * freshness + 0.35 * completeness + 0.25 * agreement

CRITICAL: confidence is NOT risk. It is computed entirely separately from
`app.risk.engine.compute_risk` and never folded into `risk_score` — the
only place confidence touches the risk score is via the explicit, named
`data_confidence_penalty` risk factor (its own 0.05-weighted component,
architecture.md §22), which is a deliberate, visible design choice, not an
accidental double-count.

These confidence weights are ORCA's own configurable heuristic
methodology, not a scientific or regulatory standard (architecture.md
§22's explicit disclaimer) — same status as the risk weights, stored in
the same file (risk_weights.yaml).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.risk.config import ConfidenceWeights


class ConfidenceInputs(BaseModel):
    """All three components are pre-normalized to [0, 1] by the caller.
    None of them may be omitted — an unknown freshness/completeness/
    agreement score must not be silently treated as fully confident (1.0)
    or fully unconfident (0.0); the caller must resolve it before calling
    `compute_confidence`.
    """

    freshness: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    agreement: float = Field(ge=0.0, le=1.0)


def compute_confidence(inputs: ConfidenceInputs, weights: ConfidenceWeights) -> float:
    confidence = (
        inputs.freshness * weights.freshness
        + inputs.completeness * weights.completeness
        + inputs.agreement * weights.agreement
    )
    # Mathematically already in [0, 1] (each input in [0,1], weights sum to
    # 1.0) — clamped only to absorb floating-point drift.
    return max(0.0, min(1.0, confidence))
