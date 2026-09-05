"""Hazard proxy calculations — architecture.md §29a, §29b.

CRITICAL — terminology discipline (architecture.md §47): these are coarse,
model/weather-code-derived PROXIES, never authoritative detection or
tracking.

- ORCA does NOT claim real-time lightning-strike detection. DAMINI
  (IITM/IMD) remains the authoritative real-time lightning-detection
  system; ORCA is not integrated with it (no public API exists).
- ORCA does NOT claim cyclone tracking. RSMC New Delhi / IMD bulletins
  remain the authoritative reference; this is a heuristic hazard
  indicator only, named `cyclone_proxy` in code — never
  `cyclone_detector` or `cyclone_tracker` (architecture.md §29a is
  explicit about this naming rule).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.risk.config import CycloneProxyWeights

# architecture.md §29b: WMO weather codes 95-99 = thunderstorm (with/without
# hail). This exact range is given by the architecture, not chosen here.
THUNDERSTORM_WMO_CODES = frozenset(range(95, 100))


def lightning_thunderstorm_proxy(weathercode: float) -> float:
    """Returns 1.0 if `weathercode` is a WMO thunderstorm code (95-99),
    else 0.0. A coarse proxy — not strike-level detection (architecture.md
    §29b).
    """
    return 1.0 if int(weathercode) in THUNDERSTORM_WMO_CODES else 0.0


class CycloneProxyInputs(BaseModel):
    """Each component pre-normalized to [0, 1] by the caller — architecture.md
    §29a lists these five signals but does not specify their individual
    normalization curves (site/model-specific), so normalization is left to
    the caller (e.g. a future Weather/Oceanographic Agent) that has the raw
    forecast series needed to compute persistence.
    """

    pressure_tendency: float = Field(ge=0.0, le=1.0)
    sustained_wind: float = Field(ge=0.0, le=1.0)
    wind_gust: float = Field(ge=0.0, le=1.0)
    spatial_persistence: float = Field(ge=0.0, le=1.0)
    temporal_persistence: float = Field(ge=0.0, le=1.0)


def cyclone_proxy(inputs: CycloneProxyInputs, weights: CycloneProxyWeights) -> float:
    """Deterministic, weighted combination of the five architecture.md §29a
    signals into a single [0, 1] hazard indicator. This is an ORCA hazard
    heuristic based on available weather-model signals, NOT authoritative
    cyclone identification or tracking.
    """
    score = (
        inputs.pressure_tendency * weights.pressure_tendency
        + inputs.sustained_wind * weights.sustained_wind
        + inputs.wind_gust * weights.wind_gust
        + inputs.spatial_persistence * weights.spatial_persistence
        + inputs.temporal_persistence * weights.temporal_persistence
    )
    return max(0.0, min(1.0, score))
