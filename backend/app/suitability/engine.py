"""The deterministic ORCA Fishing Suitability Engine — architecture.md §21.

    Zone Score = Suitability Signal + Safety (inverse of Risk Engine score)
                 + Distance + Data Confidence

Distinct from, and never overriding, the official PFZ (architecture.md
§21's hard discipline rule — see app.suitability.models.PFZReference).
"""
from __future__ import annotations

from typing import Literal

from app.suitability.config import SuitabilityWeights
from app.suitability.models import PFZReference, SuitabilityComponents, SuitabilityResult

DISTANCE_SATURATION_KM = 50.0  # beyond this, additional distance to the candidate zone no longer reduces suitability

SuitabilityCategory = Literal["HIGH", "MODERATE", "LOW", "NOT_RECOMMENDED"]


def classify_suitability_category(score: float) -> SuitabilityCategory:
    """API-presentation bucketing of this module's own continuous
    `evaluate_suitability` score — no new suitability computation.
    `SuitabilityResult` itself defines no category enum, so this is this
    engine's own documented threshold choice, the same "classify a
    continuous score into a named band" pattern `app.risk.engine
    .classify_risk_level` already uses for risk. Shared by every caller
    (map layers, Phase 3's fishing-intelligence engine) so there is exactly
    one place these thresholds are defined.
    """
    if score >= 0.66:
        return "HIGH"
    if score >= 0.40:
        return "MODERATE"
    if score >= 0.20:
        return "LOW"
    return "NOT_RECOMMENDED"


def distance_component(distance_to_zone_km: float) -> float:
    """1.0 at zero distance (the candidate zone is right here), decaying to
    0.0 at DISTANCE_SATURATION_KM and beyond — closer candidate zones are
    more operationally suitable (less fuel/time), all else equal.
    """
    if distance_to_zone_km is None:
        raise ValueError("distance_to_zone_km is required")
    if distance_to_zone_km < 0:
        raise ValueError(f"distance_to_zone_km must be >= 0, got {distance_to_zone_km}")
    return max(0.0, 1.0 - distance_to_zone_km / DISTANCE_SATURATION_KM)


def evaluate_suitability(
    *,
    signal_score: float,
    risk_score: float,
    distance_to_zone_km: float,
    confidence: float,
    weights: SuitabilityWeights,
    pfz_reference: PFZReference | None = None,
) -> SuitabilityResult:
    if not (0.0 <= signal_score <= 1.0):
        raise ValueError(f"signal_score must be in [0, 1], got {signal_score}")
    if not (0.0 <= risk_score <= 1.0):
        raise ValueError(f"risk_score must be in [0, 1], got {risk_score}")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")

    safety_score = 1.0 - risk_score
    distance_score = distance_component(distance_to_zone_km)

    components = SuitabilityComponents(
        signal=signal_score,
        safety=safety_score,
        distance=distance_score,
        data_confidence=confidence,
    )

    score = (
        components.signal * weights.signal
        + components.safety * weights.safety
        + components.distance * weights.distance
        + components.data_confidence * weights.data_confidence
    )
    score = max(0.0, min(1.0, score))

    return SuitabilityResult(
        score=score,
        components=components,
        pfz_reference=pfz_reference or PFZReference.unavailable(),
    )
