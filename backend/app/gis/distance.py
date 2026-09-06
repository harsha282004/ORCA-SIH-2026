"""Deterministic geographic distance utilities — architecture.md §26 ("A*
(Haversine heuristic)"). Phase 2 does not implement routing itself; this
module only provides the reusable distance primitives later components
(the Risk Engine's distance-based factors now, the Route Agent's A* later)
both need, so the formula is written once.

Units are always explicit in both the function name and return value —
kilometers in, kilometers out; never bare "degrees" passed around as if
they were a distance.
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon

from app.fabric.spatial import validate_point

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius — a fixed physical constant, not a tunable


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two EPSG:4326 points, in kilometers."""
    validate_point(lat1, lon1)
    validate_point(lat2, lon2)

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def offset_point_km(latitude: float, longitude: float, *, north_km: float = 0.0, west_km: float = 0.0) -> tuple[float, float]:
    """Returns a new (latitude, longitude) shifted from the given point by
    `north_km`/`west_km` (either may be negative for south/east). Used by
    architecture.md §31a's deterministic reference-resolution step (e.g.
    "20 km farther offshore") — the LLM only ever supplies the structured
    *distance*; this function performs the actual coordinate math so no
    LLM-invented coordinate ever enters the pipeline.

    Same equirectangular-projection approximation already used by
    `distance_to_polygon_km` (accurate to ~1% at the demo bbox's scale) —
    an engineering approximation, not a navigation-grade geodesic
    calculation, and documented as such everywhere it is used.
    """
    validate_point(latitude, longitude)
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(latitude))
    if km_per_deg_lon <= 0:
        raise ValueError(f"cannot offset at latitude {latitude} (too close to the pole)")

    new_latitude = latitude + (north_km / km_per_deg_lat)
    new_longitude = longitude - (west_km / km_per_deg_lon)
    return new_latitude, new_longitude


def distance_to_polygon_km(latitude: float, longitude: float, polygon: Polygon) -> float:
    """Approximate distance from a point to the nearest edge of a polygon, in
    kilometers. 0.0 if the point is inside or on the boundary.

    Method: project both the point and the polygon's exterior ring to a
    local equirectangular plane centered on the point's latitude (so 1 unit
    of longitude and 1 unit of latitude are both approximately equal to 1
    km at that latitude), then use Shapely's planar `.distance()`. This is
    accurate to within roughly 1% at the scale of the ORCA demo bbox
    (tens of km) — it is an engineering approximation for risk-scoring
    purposes, not a navigation-grade geodesic calculation.
    """
    validate_point(latitude, longitude)
    if polygon is None or polygon.is_empty:
        raise ValueError("polygon must be a non-empty geometry")

    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(latitude))
    if km_per_deg_lon <= 0:
        raise ValueError(f"cannot project at latitude {latitude} (too close to the pole)")

    def project(x_lon: float, y_lat: float) -> tuple[float, float]:
        return ((x_lon - longitude) * km_per_deg_lon, (y_lat - latitude) * km_per_deg_lat)

    point = Point(longitude, latitude)
    if polygon.contains(point) or polygon.boundary.distance(point) == 0.0:
        return 0.0

    point_km = Point(0.0, 0.0)  # the point projects to the origin by construction
    exterior_km = Polygon([project(x, y) for x, y in polygon.exterior.coords])
    return point_km.distance(exterior_km.boundary)
