"""Coordinate normalization and validation — architecture.md §18, §36.

CRS is EPSG:4326 throughout ORCA; this module is the single place that
validates a point actually is one before it can enter a
``NormalizedObservation``.
"""
from __future__ import annotations

from app.models.geo import BBox

CRS = "EPSG:4326"


class InvalidCoordinateError(ValueError):
    pass


def validate_point(latitude: float | None, longitude: float | None) -> None:
    if latitude is None or longitude is None:
        raise InvalidCoordinateError("latitude/longitude must not be None")
    if not (-90.0 <= latitude <= 90.0):
        raise InvalidCoordinateError(f"latitude {latitude} out of range [-90, 90]")
    if not (-180.0 <= longitude <= 180.0):
        raise InvalidCoordinateError(f"longitude {longitude} out of range [-180, 180]")


def point_in_bbox(latitude: float, longitude: float, bbox: BBox) -> bool:
    validate_point(latitude, longitude)
    return bbox.contains(latitude, longitude)
