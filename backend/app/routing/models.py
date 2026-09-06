"""Routing data contracts — architecture.md §26 ("Output: GeoJSON LineString,
total distance, relative risk cost, avoided hazards, geofence validation
result, per-segment evidence, route feasibility status").

No natural-language explanation lives here — that remains the Evidence &
Explanation Agent's job (§28, Phase 4+). Everything below is a structured,
typed value.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.decision.models import Decision
from app.fabric.spatial import InvalidCoordinateError, validate_point
from app.hazard.models import Hazard
from app.models.contracts import Mode, TemporalValidityStatus
from app.policy.models import SafetyGuardResult
from app.risk.engine import RiskLevel

RouteErrorCode = Literal[
    "INVALID_COORDINATES",
    "OUT_OF_DOMAIN",
    "BLOCKED_LAND_OR_GEOFENCE",
    "NO_ROUTE_FOUND",
    "STALE_DATA",
    "EXPIRED_DATA",
    "MISSING_DATA",
    "INVALID_TIMESTAMP",
    "LOW_CONFIDENCE",
    "ROUTING_RESOURCE_LIMIT",
]


class Coordinate(BaseModel):
    latitude: float
    longitude: float

    @model_validator(mode="after")
    def _validate(self) -> "Coordinate":
        try:
            validate_point(self.latitude, self.longitude)
        except InvalidCoordinateError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RouteRequest(BaseModel):
    """architecture.md §5 (Phase 3 task spec): origin, destination, and any
    required temporal context. `requested_time` resolves which environmental
    data window applies (architecture.md §17 Temporal Validity Gate) —
    defaults to "now" if omitted.
    """

    origin: Coordinate
    destination: Coordinate
    requested_time: datetime | None = None
    # Phase 5 (task §12) — 1 (default) reproduces Phase 3/4's exact
    # single-route response; >1 additionally runs
    # `app.routing.alternatives.generate_route_alternatives` (bounded, see
    # that module's own docstring for why this is never "hundreds of
    # routes"). Never negative/zero — validated below.
    max_alternatives: int = Field(default=1, ge=1, le=5)


class RouteValidationIssue(BaseModel):
    code: RouteErrorCode
    message: str
    details: dict = Field(default_factory=dict)


class RouteCellRef(BaseModel):
    """One cell along the reconstructed path."""

    cell_id: str
    row: int
    col: int
    latitude: float
    longitude: float
    risk_score: float | None
    hazard_score: float | None
    geofence_soft_penalty: float


class RouteMetrics(BaseModel):
    """ORCA engineering metrics — not an official maritime route-safety
    certification (architecture.md §22/§26 disclaimer pattern).
    """

    total_distance_km: float
    distance_cost: float
    environmental_risk_cost: float
    hazard_cost: float
    geofence_cost: float
    # Phase 5 — always 0.0 unless this route was generated via
    # app.routing.alternatives as a deliberately-diverse 2nd/3rd option (see
    # app.routing.costs' module docstring). Exposed so a route's total_cost
    # is always fully explained by its own breakdown, never a silent gap.
    alternative_penalty_cost: float = 0.0
    total_cost: float
    cell_count: int
    average_risk_score: float | None
    max_risk_score: float | None


class RouteResult(BaseModel):
    route_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    origin: Coordinate
    destination: Coordinate

    path_coordinates: list[Coordinate]
    path_cells: list[RouteCellRef]

    metrics: RouteMetrics
    feasibility_status: Literal["FEASIBLE"] = "FEASIBLE"

    grid_resolution_km: float
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    mode: Mode
    data_quality: Literal["fixture", "live"]
    temporal_validity: TemporalValidityStatus
    confidence: float

    disclaimer: str = (
        "This route is optimal with respect to ORCA's own configured deterministic "
        "cost model. It is not an official maritime navigation recommendation and is "
        "not guaranteed to be the globally safest possible route."
    )

    def to_geojson_linestring(self) -> dict:
        return {
            "type": "LineString",
            "coordinates": [[c.longitude, c.latitude] for c in self.path_coordinates],
        }


class RankedRoute(BaseModel):
    """Phase 5 (task §12/§13/§14) — one alternative, fully evaluated
    through the SAME deterministic pipeline every route goes through:
    `calculate_route` -> `hazards_near_route` -> `app.routing.safety
    .evaluate_route_safety`. `label` ("A"/"B"/"C", assigned in the order
    routes were generated — the primary/optimal route is always "A") is
    presentation-only; it carries no ranking meaning by itself, only
    `RouteComparisonResult.recommended_label` does.
    """

    label: str
    route: RouteResult
    risk_level: RiskLevel
    decision: Decision
    safety: SafetyGuardResult
    hazards_near_route: list[Hazard]
    hazard_source_tier: Literal["live", "cached", "unavailable"]


class RouteComparisonResult(BaseModel):
    """Deterministic comparison output (task §14) — `recommended_label` is
    computed by `app.routing.comparison.compare_routes`, never by an LLM;
    `reason` is a template string built from the same real numbers shown in
    `routes`, not a natural-language generation (Groq may re-phrase this
    for a conversational answer, but never invent or override it).
    """

    routes: list[RankedRoute]
    recommended_label: str | None
    reason: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
