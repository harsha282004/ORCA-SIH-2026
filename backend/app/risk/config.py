"""Risk Engine configuration loader — architecture.md §22.

Weights are never hard-coded inside calculation functions (architecture.md
§4's "Configuration over hardcoding" principle) — they are loaded once
from ``risk_weights.yaml`` into typed, validated models. A weight set that
does not sum to 1.0 fails fast at load time; it is never silently
re-normalized (reproducibility — architecture.md §22's explicit
methodology disclaimer depends on the configured numbers actually being
the numbers used).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

_WEIGHT_SUM_TOLERANCE = 1e-6

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "risk_weights.yaml"


class WeightSumError(ValueError):
    """Raised when a set of weights does not sum to 1.0. Fail fast — never
    silently re-normalized.
    """


def check_weights_sum_to_one(name: str, weights: dict[str, float]) -> None:
    """Shared by every weight-set model in this project (risk, confidence,
    cyclone proxy, suitability) so the fail-fast rule is enforced
    identically everywhere, not re-implemented per module.
    """
    total = sum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise WeightSumError(f"{name} must sum to 1.0, got {total} for {weights}")


class RiskWeights(BaseModel):
    wave: float
    wind: float
    advisory_or_hazard_flag: float
    lightning_thunderstorm_proxy: float
    restricted_zone_distance: float
    coast_distance: float
    data_confidence_penalty: float

    @model_validator(mode="after")
    def _sum_to_one(self) -> "RiskWeights":
        check_weights_sum_to_one("risk_weights", self.model_dump())
        return self


class RiskThresholds(BaseModel):
    low_max: float
    moderate_max: float

    @model_validator(mode="after")
    def _ordered(self) -> "RiskThresholds":
        if not (0.0 < self.low_max < self.moderate_max <= 1.0):
            raise ValueError(
                f"risk_thresholds must satisfy 0 < low_max < moderate_max <= 1.0, "
                f"got low_max={self.low_max}, moderate_max={self.moderate_max}"
            )
        return self


class ConfidenceWeights(BaseModel):
    freshness: float
    completeness: float
    agreement: float

    @model_validator(mode="after")
    def _sum_to_one(self) -> "ConfidenceWeights":
        check_weights_sum_to_one("confidence_weights", self.model_dump())
        return self


class CycloneProxyWeights(BaseModel):
    pressure_tendency: float
    sustained_wind: float
    wind_gust: float
    spatial_persistence: float
    temporal_persistence: float

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CycloneProxyWeights":
        check_weights_sum_to_one("cyclone_proxy_weights", self.model_dump())
        return self


class SafetyConfig(BaseModel):
    min_confidence_threshold: float

    @model_validator(mode="after")
    def _bounded(self) -> "SafetyConfig":
        if not (0.0 <= self.min_confidence_threshold <= 1.0):
            raise ValueError(f"min_confidence_threshold must be in [0, 1], got {self.min_confidence_threshold}")
        return self


class RiskConfig(BaseModel):
    risk_weights: RiskWeights
    risk_thresholds: RiskThresholds
    confidence_weights: ConfidenceWeights
    cyclone_proxy_weights: CycloneProxyWeights
    safety: SafetyConfig


def load_risk_config(path: Path | None = None) -> RiskConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RiskConfig.model_validate(raw)


@lru_cache
def get_risk_config() -> RiskConfig:
    return load_risk_config()
