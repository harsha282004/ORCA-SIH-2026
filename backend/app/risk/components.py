"""Deterministic risk component normalization — architecture.md §22.

Each function maps one raw physical/categorical input to a normalized
value in [0, 1] ("normalized_factor" in architecture.md §22's output
schema). The architecture specifies the seven component NAMES and their
WEIGHTS exactly (see risk_weights.yaml) but does not specify the exact
raw-to-normalized curve for each — it gives a single worked example
(wave=1.4m -> 0.55, wind=16kt -> 0.40, ...) to demonstrate the weighted-sum
formula, not to fix a normalization function. The curves below are Phase
2's own documented engineering choice, consistent with architecture.md
§22's explicit statement that this whole methodology is "ORCA's own
configurable heuristic methodology, not a validated scientific or
regulatory standard." Saturation points are configurable constants below,
not buried magic numbers.

All inputs are in the canonical units Phase 1 already established
(app.fabric.units): wind/current speed in m/s, wave height in m,
distances in km.

Missing data is never silently treated as zero risk — every function
raises on `None`/invalid input rather than substituting a default. The
caller (or, eventually, the Safety Guard's missing-data check) is
responsible for deciding what to do when a raw value is unavailable.
"""
from __future__ import annotations

from typing import Literal

# --- Documented saturation points (Phase 2 engineering config, not a
# scientific optimum) ---
WAVE_SATURATION_M = 3.0  # wave height at/above which wave risk is treated as maximal
WIND_SATURATION_MS = 20.0  # wind speed at/above which wind risk is treated as maximal
RESTRICTED_ZONE_SATURATION_KM = 10.0  # distance beyond which proximity to a restricted zone no longer adds risk
COAST_DISTANCE_SATURATION_KM = 80.0  # offshore distance at/beyond which isolation risk is treated as maximal

AdvisoryLevel = Literal["none", "low", "moderate", "high"]
_ADVISORY_LEVEL_SCORES: dict[AdvisoryLevel, float] = {
    "none": 0.0,
    "low": 1.0 / 3.0,
    "moderate": 2.0 / 3.0,
    "high": 1.0,
}


def _validate_normalized(name: str, value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} produced an out-of-range normalized value: {value}")
    return value


def wave_risk(wave_height_m: float) -> float:
    """Linear ramp 0m -> 0.0, saturating to 1.0 at WAVE_SATURATION_M."""
    if wave_height_m is None:
        raise ValueError("wave_height_m is required")
    if wave_height_m < 0:
        raise ValueError(f"wave_height_m must be >= 0, got {wave_height_m}")
    return _validate_normalized("wave_risk", min(wave_height_m / WAVE_SATURATION_M, 1.0))


def wind_risk(wind_speed_ms: float) -> float:
    """Linear ramp 0 m/s -> 0.0, saturating to 1.0 at WIND_SATURATION_MS."""
    if wind_speed_ms is None:
        raise ValueError("wind_speed_ms is required")
    if wind_speed_ms < 0:
        raise ValueError(f"wind_speed_ms must be >= 0, got {wind_speed_ms}")
    return _validate_normalized("wind_risk", min(wind_speed_ms / WIND_SATURATION_MS, 1.0))


def advisory_or_hazard_risk(advisory_level: AdvisoryLevel, cyclone_proxy_score: float | None = None) -> float:
    """Combines an official-advisory severity level with the (optional)
    cyclone proxy score (architecture.md §22: "includes cyclone-proxy +
    active official advisory") — whichever signal is more severe dominates,
    since either alone is sufficient reason for concern.
    """
    if advisory_level not in _ADVISORY_LEVEL_SCORES:
        raise ValueError(f"unknown advisory_level: {advisory_level!r}")
    advisory_score = _ADVISORY_LEVEL_SCORES[advisory_level]

    if cyclone_proxy_score is None:
        combined = advisory_score
    else:
        if not (0.0 <= cyclone_proxy_score <= 1.0):
            raise ValueError(f"cyclone_proxy_score must be in [0, 1], got {cyclone_proxy_score}")
        combined = max(advisory_score, cyclone_proxy_score)

    return _validate_normalized("advisory_or_hazard_risk", combined)


def restricted_zone_distance_risk(distance_km: float) -> float:
    """Inverse-decay: 1.0 right at a restricted-zone boundary, decaying
    linearly to 0.0 at RESTRICTED_ZONE_SATURATION_KM and beyond — closer to
    a restricted zone means more risk of accidental incursion.
    """
    if distance_km is None:
        raise ValueError("distance_km is required")
    if distance_km < 0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")
    return _validate_normalized(
        "restricted_zone_distance_risk", max(0.0, 1.0 - distance_km / RESTRICTED_ZONE_SATURATION_KM)
    )


def coast_distance_risk(distance_km: float) -> float:
    """Linear ramp 0km -> 0.0, saturating to 1.0 at COAST_DISTANCE_SATURATION_KM
    — farther offshore means less immediate rescue/response access, so risk
    increases with distance from the coast. This direction (risk increases
    with distance, rather than the grounding-risk direction of "too close to
    shore") is a documented Phase 2 interpretation, chosen because the
    architecture's own worked example (8km -> a low 0.10 contribution) is
    only consistent with an increasing-with-distance curve, not a
    decreasing one.
    """
    if distance_km is None:
        raise ValueError("distance_km is required")
    if distance_km < 0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")
    return _validate_normalized("coast_distance_risk", min(distance_km / COAST_DISTANCE_SATURATION_KM, 1.0))


def data_confidence_penalty_risk(confidence: float) -> float:
    """The Risk Engine's own confidence penalty (architecture.md §22:
    "penalizes low-confidence/stale inputs directly in the score") — the
    complement of confidence. This is distinct from, and never combined
    with, the standalone `confidence` value computed by
    app.reasoning.confidence; it is one more named risk factor, weighted
    at 0.05 like any other.
    """
    if confidence is None:
        raise ValueError("confidence is required")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")
    return _validate_normalized("data_confidence_penalty_risk", 1.0 - confidence)
