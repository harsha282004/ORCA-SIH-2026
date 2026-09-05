"""Suitability Engine weight configuration — architecture.md §21."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from app.risk.config import check_weights_sum_to_one

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "suitability_weights.yaml"


class SuitabilityWeights(BaseModel):
    signal: float
    safety: float
    distance: float
    data_confidence: float

    @model_validator(mode="after")
    def _sum_to_one(self) -> "SuitabilityWeights":
        check_weights_sum_to_one("suitability_weights", self.model_dump())
        return self


def load_suitability_weights(path: Path | None = None) -> SuitabilityWeights:
    config_path = path or DEFAULT_CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SuitabilityWeights.model_validate(raw["suitability_weights"])


@lru_cache
def get_suitability_weights() -> SuitabilityWeights:
    return load_suitability_weights()
