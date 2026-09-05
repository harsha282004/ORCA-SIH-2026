"""Deterministic candidate-cell grid generation — architecture.md §18
("query bounding box is discretized into a grid of candidate cells,
resolution tunable, ~2-5 km for coastal MVP") and §33's `risk_cells`
concept.

This is grid *geometry* only — no risk value is attached here (that is
`app.risk.risk_cell`'s job). Resolution is configuration, not a claimed
scientific optimum (see architecture.md §27 discipline).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from shapely.geometry import Polygon

from app.models.geo import BBox

KM_PER_DEGREE_LAT = 111.32


@dataclass(frozen=True)
class GridDimensions:
    n_rows: int
    n_cols: int
    lat_step: float
    lon_step: float


def grid_dimensions(bbox: BBox, *, resolution_km: float) -> GridDimensions:
    """The row/column layout `generate_grid` uses for a given (bbox,
    resolution_km) pair — extracted so other callers (Phase 3's routing
    grid, which needs to locate which cell a coordinate falls into) can
    stay byte-for-byte consistent with generate_grid's own layout without
    re-deriving or duplicating this formula.
    """
    if resolution_km <= 0:
        raise ValueError(f"resolution_km must be positive, got {resolution_km}")

    lat_span_km = (bbox.max_lat - bbox.min_lat) * KM_PER_DEGREE_LAT
    mid_lat = (bbox.min_lat + bbox.max_lat) / 2.0
    km_per_degree_lon = KM_PER_DEGREE_LAT * math.cos(math.radians(mid_lat))
    if km_per_degree_lon <= 0:
        raise ValueError(f"cannot rasterize a bbox centered at latitude {mid_lat}")
    lon_span_km = (bbox.max_lon - bbox.min_lon) * km_per_degree_lon

    n_rows = max(1, math.ceil(lat_span_km / resolution_km))
    n_cols = max(1, math.ceil(lon_span_km / resolution_km))

    lat_step = (bbox.max_lat - bbox.min_lat) / n_rows
    lon_step = (bbox.max_lon - bbox.min_lon) / n_cols

    return GridDimensions(n_rows=n_rows, n_cols=n_cols, lat_step=lat_step, lon_step=lon_step)


class GridCell(BaseModel):
    """One candidate cell's geometry. `row`/`col` make cell identity and
    adjacency deterministic and reproducible from the same bbox+resolution.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    cell_id: str
    row: int
    col: int
    geometry: Polygon
    centroid_lat: float
    centroid_lon: float

    def to_geojson(self) -> dict:
        return {
            "type": "Feature",
            "properties": {"cell_id": self.cell_id, "row": self.row, "col": self.col},
            "geometry": {
                "type": "Polygon",
                "coordinates": [list(self.geometry.exterior.coords)],
            },
        }


def generate_grid(bbox: BBox, *, resolution_km: float) -> list[GridCell]:
    """Rasterize `bbox` into a deterministic grid of GridCells, each
    approximately `resolution_km` x `resolution_km`. Cell (0, 0) is the
    southwest corner; rows increase northward, columns eastward — always
    the same layout for the same (bbox, resolution_km) pair.
    """
    dims = grid_dimensions(bbox, resolution_km=resolution_km)
    n_rows, n_cols, lat_step, lon_step = dims.n_rows, dims.n_cols, dims.lat_step, dims.lon_step

    cells: list[GridCell] = []
    for row in range(n_rows):
        for col in range(n_cols):
            south = bbox.min_lat + row * lat_step
            north = south + lat_step
            west = bbox.min_lon + col * lon_step
            east = west + lon_step

            polygon = Polygon([(west, south), (east, south), (east, north), (west, north), (west, south)])
            cells.append(
                GridCell(
                    cell_id=f"r{row}c{col}",
                    row=row,
                    col=col,
                    geometry=polygon,
                    centroid_lat=(south + north) / 2.0,
                    centroid_lon=(west + east) / 2.0,
                )
            )
    return cells
