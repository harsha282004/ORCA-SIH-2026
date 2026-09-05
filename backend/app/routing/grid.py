"""Routing grid adapter — wraps Phase 2's `app.gis.grid.GridCell` geometry
with the navigability/risk/hazard annotations A* needs, without
duplicating grid generation or geofence logic.

Land masking is NOT special-cased here: `GeofenceCategory.LAND` is already
one of Phase 2's HARD geofence categories, so a land polygon blocks a cell
through the exact same `evaluate_point_against_geofences` pathway as a
protected area or international boundary — there is no separate
land-specific rule inside routing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

from app.gis.geofence import Geofence, evaluate_polygon_against_geofences, nearest_hard_geofence_distance_km
from app.gis.grid import GridCell, generate_grid, grid_dimensions
from app.models.geo import BBox
from app.risk.components import restricted_zone_distance_risk


class EnvironmentalScoreProvider(Protocol):
    """A callable mapping a grid cell to a normalized [0, 1] score. Phase 3
    test fixtures implement this directly; a later phase's live per-cell
    Marine Data Fabric lookup can implement the exact same interface
    without A* or the cost function ever changing (architecture.md Phase 3
    task spec §31).
    """

    def __call__(self, cell: GridCell) -> float: ...


class RoutingNode(BaseModel):
    """One grid cell annotated for pathfinding — architecture.md Phase 3
    task spec §9: row/col identity, center coordinate, geometry, navigable
    state, risk, hazard, geofence state, cost metadata.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    cell: GridCell
    navigable: bool
    block_reason: str | None = None
    risk_score: float | None = None
    hazard_score: float | None = None
    geofence_soft_penalty: float = 0.0

    @property
    def row(self) -> int:
        return self.cell.row

    @property
    def col(self) -> int:
        return self.cell.col

    @property
    def cell_id(self) -> str:
        return self.cell.cell_id


def build_routing_grid(
    bbox: BBox,
    *,
    resolution_km: float,
    geofences: list[Geofence],
    risk_provider: EnvironmentalScoreProvider,
    hazard_provider: EnvironmentalScoreProvider,
    at_time: datetime | None = None,
) -> dict[tuple[int, int], RoutingNode]:
    """Builds the full annotated grid once per route calculation. Returns a
    dict keyed by (row, col) for O(1) neighbor lookups in A*.
    """
    cells = generate_grid(bbox, resolution_km=resolution_km)
    nodes: dict[tuple[int, int], RoutingNode] = {}

    for cell in cells:
        # Polygon-vs-polygon intersection, not just the centroid point —
        # see app.gis.geofence.evaluate_polygon_against_geofences for why
        # a centroid-only check can miss a hard obstacle thinner than one
        # grid cell.
        geofence_result = evaluate_polygon_against_geofences(cell.geometry, geofences, at_time=at_time)
        if geofence_result.blocked:
            nodes[(cell.row, cell.col)] = RoutingNode(
                cell=cell, navigable=False, block_reason=geofence_result.reason
            )
            continue

        soft_distance_km = nearest_hard_geofence_distance_km(
            cell.centroid_lat, cell.centroid_lon, geofences, at_time=at_time
        )
        geofence_soft_penalty = restricted_zone_distance_risk(soft_distance_km) if soft_distance_km is not None else 0.0

        nodes[(cell.row, cell.col)] = RoutingNode(
            cell=cell,
            navigable=True,
            risk_score=risk_provider(cell),
            hazard_score=hazard_provider(cell),
            geofence_soft_penalty=geofence_soft_penalty,
        )

    return nodes


def locate_cell(bbox: BBox, *, resolution_km: float, latitude: float, longitude: float) -> tuple[int, int]:
    """The (row, col) of the grid cell containing (latitude, longitude),
    using the exact same layout as `app.gis.grid.generate_grid` (via the
    shared `grid_dimensions` helper) so a point validated against the grid
    and a point rasterized into the grid can never disagree on which cell
    it belongs to.
    """
    dims = grid_dimensions(bbox, resolution_km=resolution_km)

    row = int((latitude - bbox.min_lat) / dims.lat_step)
    col = int((longitude - bbox.min_lon) / dims.lon_step)

    row = min(max(row, 0), dims.n_rows - 1)
    col = min(max(col, 0), dims.n_cols - 1)
    return row, col


def zero_score_provider(_cell: GridCell) -> float:
    """A trivial EnvironmentalScoreProvider — used where a caller
    genuinely has no risk/hazard signal to contribute (e.g. isolating
    distance-only routing behavior in tests).
    """
    return 0.0
