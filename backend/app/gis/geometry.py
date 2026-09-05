"""Deterministic geometry validation — architecture.md §18, §25, §36.

CRS is EPSG:4326 throughout ORCA. Point validation is Phase 1's job
(``app.fabric.spatial.validate_point``) and is reused here rather than
duplicated; this module adds polygon-level validity, since Phase 1 never
needed polygons (it only ever handled point observations).

Geometry is never silently "fixed" — a repair is only ever performed when
the caller explicitly asks for it via ``validate_polygon(..., repair=True)``,
and the fact that a repair happened is always reported back, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely import make_valid
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry

from app.fabric.spatial import CRS, InvalidCoordinateError, validate_point

__all__ = [
    "CRS",
    "InvalidCoordinateError",
    "InvalidGeometryError",
    "PolygonValidationResult",
    "validate_point",
    "validate_polygon",
    "polygon_from_geojson",
]


class InvalidGeometryError(ValueError):
    """Raised for a structurally invalid or empty geometry that was not repaired."""


@dataclass
class PolygonValidationResult:
    geometry: Polygon
    was_repaired: bool
    original_valid: bool


def polygon_from_geojson(geojson: dict) -> Polygon:
    """Parse a GeoJSON Polygon dict into a Shapely Polygon. Raises
    InvalidGeometryError on malformed input — never silently returns an
    empty or partial geometry.
    """
    try:
        geometry = shape(geojson)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise InvalidGeometryError(f"malformed GeoJSON geometry: {exc}") from exc

    if not isinstance(geometry, Polygon):
        raise InvalidGeometryError(f"expected a Polygon, got {geometry.geom_type}")

    return geometry


def validate_polygon(geometry: BaseGeometry, *, repair: bool = False) -> PolygonValidationResult:
    """Validate a polygon's geometric validity (per Shapely/OGC rules — e.g.
    no self-intersections) and non-emptiness.

    If the geometry is invalid and `repair` is False (the default), raises
    InvalidGeometryError. If `repair` is True, attempts `shapely.make_valid`
    and returns a PolygonValidationResult with `was_repaired=True` — the
    caller always knows a repair happened; it is never silent.
    """
    if geometry is None:
        raise InvalidGeometryError("geometry is None")
    if geometry.is_empty:
        raise InvalidGeometryError("geometry is empty")

    original_valid = geometry.is_valid

    if original_valid:
        if not isinstance(geometry, Polygon):
            raise InvalidGeometryError(f"expected a Polygon, got {geometry.geom_type}")
        return PolygonValidationResult(geometry=geometry, was_repaired=False, original_valid=True)

    if not repair:
        raise InvalidGeometryError(
            f"geometry is invalid ({geometry}); pass repair=True to attempt shapely.make_valid"
        )

    repaired = make_valid(geometry)
    if repaired.is_empty:
        raise InvalidGeometryError("geometry remained empty after make_valid repair")
    if repaired.geom_type not in ("Polygon", "MultiPolygon"):
        raise InvalidGeometryError(f"repair produced an unusable geometry type: {repaired.geom_type}")
    if repaired.geom_type == "MultiPolygon":
        # Take the largest component — a documented, explicit choice, not a silent one.
        repaired = max(repaired.geoms, key=lambda g: g.area)

    return PolygonValidationResult(geometry=repaired, was_repaired=True, original_valid=False)
