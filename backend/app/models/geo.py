"""Geographic bounding box — used to scope the demo region (architecture.md §44).

CRS is always EPSG:4326 (architecture.md §18, §36).
"""
from __future__ import annotations

from pydantic import BaseModel, model_validator


class BBox(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @model_validator(mode="after")
    def _validate_bounds(self) -> "BBox":
        if not (-90.0 <= self.min_lat < self.max_lat <= 90.0):
            raise ValueError(f"invalid latitude bounds: min_lat={self.min_lat}, max_lat={self.max_lat}")
        if not (-180.0 <= self.min_lon < self.max_lon <= 180.0):
            raise ValueError(f"invalid longitude bounds: min_lon={self.min_lon}, max_lon={self.max_lon}")
        return self

    def center(self) -> tuple[float, float]:
        return ((self.min_lat + self.max_lat) / 2.0, (self.min_lon + self.max_lon) / 2.0)

    def contains(self, latitude: float, longitude: float) -> bool:
        return self.min_lat <= latitude <= self.max_lat and self.min_lon <= longitude <= self.max_lon
