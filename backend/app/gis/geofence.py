"""Deterministic geofence classification — architecture.md §25.

Hard vs soft is an architectural distinction, not a Phase 2 invention:

    HARD  (§25): land, restricted/protected area, international boundary
          crossing — route cost = infinity / cell removed from candidates.
    SOFT  (§25): high waves, strong wind, strong currents, long distance
          from coast — increases risk score, never blocks outright.

Soft constraints are continuous risk factors (handled by app.risk), not
polygon membership checks — so this module only classifies HARD polygon
membership; the "distance-based" soft factors (restricted-zone distance,
coast distance) live as Risk Engine components (app/risk/components.py)
that happen to consume `nearest_hard_geofence_distance_km` from here.

`is_authoritative` mirrors architecture.md §25 exactly: it is what
prevents a synthetic/illustrative polygon (e.g. a demo CRZ buffer) from
ever being treated the same as a real WDPA/EEZ boundary.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator
from shapely.geometry import Point, Polygon

from app.fabric.spatial import validate_point
from app.gis.distance import distance_to_polygon_km
from app.gis.geometry import polygon_from_geojson


class GeofenceCategory(str, Enum):
    LAND = "land"
    PROTECTED_AREA = "protected_area"
    INTERNATIONAL_BOUNDARY = "international_boundary"
    RESTRICTED_ZONE = "restricted_zone"  # e.g. a time-bound fishing-ban zone, when active


HARD_CATEGORIES = frozenset(
    {
        GeofenceCategory.LAND,
        GeofenceCategory.PROTECTED_AREA,
        GeofenceCategory.INTERNATIONAL_BOUNDARY,
        GeofenceCategory.RESTRICTED_ZONE,
    }
)


class ConstraintType(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class Geofence(BaseModel):
    """A single geofence polygon. Not persisted here — Phase 1 did not
    acquire the real WDPA/EEZ/coastline datasets this would eventually be
    loaded from (see docs/demo_region.md); Phase 2 tests construct these
    from fixture GeoJSON only.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    category: GeofenceCategory
    geometry: Polygon
    is_authoritative: bool
    source: str
    active_from: datetime | None = None
    active_to: datetime | None = None

    @field_validator("geometry", mode="before")
    @classmethod
    def _parse_geometry(cls, v):
        if isinstance(v, Polygon):
            return v
        if isinstance(v, dict):
            return polygon_from_geojson(v)
        raise ValueError("geometry must be a Shapely Polygon or a GeoJSON Polygon dict")

    def is_active_at(self, at_time: datetime | None) -> bool:
        if self.active_from is None and self.active_to is None:
            return True
        if at_time is None:
            # A time-bound geofence with no query time given is treated as
            # active — conservative default, never silently ignored.
            return True
        if self.active_from is not None and at_time < self.active_from:
            return False
        if self.active_to is not None and at_time > self.active_to:
            return False
        return True


class GeofenceCheckResult(BaseModel):
    allowed: bool
    blocked: bool
    constraint_type: ConstraintType | None = None
    reason: str | None = None
    matched_geofence_id: str | None = None
    matched_geofence_name: str | None = None
    distance_km: float | None = None
    source: str | None = None
    is_authoritative: bool | None = None


def evaluate_point_against_geofences(
    latitude: float,
    longitude: float,
    geofences: list[Geofence],
    *,
    at_time: datetime | None = None,
) -> GeofenceCheckResult:
    """Hard-block check only (architecture.md §25's HARD category). Returns
    the first matching active hard geofence — deterministic given a fixed
    ordering of `geofences`, never a random pick among ties.
    """
    validate_point(latitude, longitude)
    point = Point(longitude, latitude)

    for fence in geofences:
        if fence.category not in HARD_CATEGORIES:
            continue
        if not fence.is_active_at(at_time):
            continue
        # `.contains()` alone misses boundary points (DE-9IM: contains
        # requires interior intersection), so a point exactly on the edge
        # is checked separately — a fishing vessel at the boundary line is
        # still "in" the restricted zone for safety purposes.
        on_boundary = fence.geometry.boundary.distance(point) == 0.0
        if fence.geometry.contains(point) or on_boundary:
            return GeofenceCheckResult(
                allowed=False,
                blocked=True,
                constraint_type=ConstraintType.HARD,
                reason=f"point falls inside {fence.category.value} geofence {fence.name!r}",
                matched_geofence_id=fence.id,
                matched_geofence_name=fence.name,
                distance_km=0.0,
                source=fence.source,
                is_authoritative=fence.is_authoritative,
            )

    return GeofenceCheckResult(allowed=True, blocked=False)


def evaluate_polygon_against_geofences(
    polygon: Polygon,
    geofences: list[Geofence],
    *,
    at_time: datetime | None = None,
) -> GeofenceCheckResult:
    """Hard-block check for an entire area, not a single point — added for
    Phase 3's routing grid. A single-point/centroid check is the wrong
    granularity for masking a grid cell: a hard geofence thinner than one
    grid cell (a narrow strait, a slim protected strip) can sit entirely
    between two cell centroids and never trigger `evaluate_point_against_geofences`,
    silently leaving a "hole" a route could pass through. A cell counts as
    blocked here if a HARD geofence intersects ANY part of it.
    """
    for fence in geofences:
        if fence.category not in HARD_CATEGORIES:
            continue
        if not fence.is_active_at(at_time):
            continue
        if fence.geometry.intersects(polygon):
            return GeofenceCheckResult(
                allowed=False,
                blocked=True,
                constraint_type=ConstraintType.HARD,
                reason=f"cell intersects {fence.category.value} geofence {fence.name!r}",
                matched_geofence_id=fence.id,
                matched_geofence_name=fence.name,
                distance_km=0.0,
                source=fence.source,
                is_authoritative=fence.is_authoritative,
            )

    return GeofenceCheckResult(allowed=True, blocked=False)


def nearest_hard_geofence_distance_km(
    latitude: float,
    longitude: float,
    geofences: list[Geofence],
    *,
    at_time: datetime | None = None,
) -> float | None:
    """Distance in km to the nearest active HARD geofence, or None if there
    are no active hard geofences to measure against (explicit absence, not
    a fabricated large number).
    """
    validate_point(latitude, longitude)

    distances = [
        distance_to_polygon_km(latitude, longitude, fence.geometry)
        for fence in geofences
        if fence.category in HARD_CATEGORIES and fence.is_active_at(at_time)
    ]
    return min(distances) if distances else None
