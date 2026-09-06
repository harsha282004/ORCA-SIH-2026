"""Routing configuration loader — architecture.md §26.

Cost weights and resource limits are centralized here, never scattered as
magic numbers through astar.py/costs.py. The minimum-confidence threshold
routing enforces is NOT re-declared here — it reuses
app.risk.config.RiskConfig.safety.min_confidence_threshold directly
(architecture.md Phase 3 task spec §29: "reuse Phase 2 confidence
calculation... do not invent a second confidence formula").
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "routing_config.yaml"


class GridConfig(BaseModel):
    resolution_km: float
    max_cells: int

    @model_validator(mode="after")
    def _positive(self) -> "GridConfig":
        if self.resolution_km <= 0:
            raise ValueError(f"grid.resolution_km must be positive, got {self.resolution_km}")
        if self.max_cells <= 0:
            raise ValueError(f"grid.max_cells must be positive, got {self.max_cells}")
        return self


class SearchConfig(BaseModel):
    max_expanded_nodes: int

    @model_validator(mode="after")
    def _positive(self) -> "SearchConfig":
        if self.max_expanded_nodes <= 0:
            raise ValueError(f"search.max_expanded_nodes must be positive, got {self.max_expanded_nodes}")
        return self


class RoutingCostWeights(BaseModel):
    distance: float
    environmental_risk: float
    hazard: float
    geofence_soft: float
    # Phase 5 — see app.routing.grid.RoutingNode.alternative_penalty and
    # app.routing.costs' module docstring for the exact formula. Defaults to
    # 0.0 so every pre-Phase-5 construction of this model (many exist across
    # tests and routing_config.yaml) is unaffected; only
    # app.routing.alternatives ever sets a nonzero per-cell penalty.
    alternative_penalty: float = 0.0

    @model_validator(mode="after")
    def _non_negative(self) -> "RoutingCostWeights":
        for name, value in self.model_dump().items():
            if value < 0:
                raise ValueError(f"cost_weights.{name} must be >= 0, got {value}")
        if self.distance <= 0:
            # distance must be strictly positive: the A* heuristic is scaled
            # by this weight to remain admissible (see routing/astar.py) —
            # a zero/negative distance weight would break that guarantee.
            raise ValueError(f"cost_weights.distance must be > 0, got {self.distance}")
        return self


class RoutingConfig(BaseModel):
    grid: GridConfig
    search: SearchConfig
    cost_weights: RoutingCostWeights


def load_routing_config(path: Path | None = None) -> RoutingConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RoutingConfig.model_validate(raw)


@lru_cache
def get_routing_config() -> RoutingConfig:
    return load_routing_config()
