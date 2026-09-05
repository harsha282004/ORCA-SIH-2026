"""GIS & Geofencing Agent — architecture.md §10, §25, §36.

Deterministic spatial intelligence only — no LLM, no natural-language
output. This agent does not implement any new geometry algorithm; it is a
typed service boundary over Phase 2's `app.gis` package (geometry,
distance, geofence, grid) and Phase 3's `app.gis.geofence.evaluate_polygon_against_geofences`.

**No real coastline/WDPA/EEZ data exists.** Phase 1 never acquired Natural
Earth, GEBCO, WDPA, or Marine Regions data (see docs/demo_region.md) — the
`static_layer_sources` registry (Phase 1, `app.data.storage`) records
every one of them as `not_acquired`. This agent's `get_geofences()`
therefore serves the same explicit, labeled fixture geometry Phase 3's
routing endpoint already used (`app.routing.fixtures`) — reused here, not
duplicated — and `get_static_dataset_status()` genuinely queries the
registry (gracefully degrading if PostGIS is unreachable) rather than
assuming or fabricating an answer.
"""
from __future__ import annotations

from datetime import datetime

from app.agents.common.cache import AgentCache
from app.config import Settings, get_settings
from app.fabric.spatial import InvalidCoordinateError, validate_point
from app.gis.distance import haversine_km
from app.gis.geofence import Geofence, GeofenceCheckResult, evaluate_point_against_geofences, nearest_hard_geofence_distance_km
from app.gis.grid import GridCell, generate_grid
from app.models.geo import BBox
from app.routing.fixtures import DEMO_FIXTURE_GEOFENCES
from app.services.cache import get_client as get_redis_client

KNOWN_STATIC_DATASETS = ("natural_earth_coastline", "gebco_bathymetry", "wdpa_protected_areas", "marine_regions_eez")


class GISGeofencingAgent:
    def __init__(self, *, cache: AgentCache | None = None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._cache = cache or AgentCache(_redis_client_or_none(), ttl_seconds=self._settings.gis_cache_ttl_seconds)

    # --- Coordinate / geometry -------------------------------------------

    def validate_coordinate(self, latitude: float, longitude: float) -> None:
        validate_point(latitude, longitude)  # raises InvalidCoordinateError

    def distance_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        return haversine_km(lat1, lon1, lat2, lon2)

    def generate_candidate_grid(self, bbox: BBox, *, resolution_km: float) -> list[GridCell]:
        return generate_grid(bbox, resolution_km=resolution_km)

    # --- Geofencing --------------------------------------------------------

    def get_geofences(self, *, bbox: BBox | None = None) -> tuple[list[Geofence], dict]:
        """Returns (geofences, metadata). `bbox` is currently unused for
        filtering (the only registered geofences are a small fixture set
        that already sits inside the demo bbox) — accepted so a later
        phase backed by a real, larger geofence table can filter by bbox
        without changing this method's signature.
        """
        metadata = {
            "is_authoritative": False,
            "source_tier": "synthetic",
            "count": len(DEMO_FIXTURE_GEOFENCES),
            "disclaimer": "DEMO DATA / SIMULATION — NOT LIVE DATA: fixture geofences, not real coastline/WDPA/EEZ data",
        }
        return list(DEMO_FIXTURE_GEOFENCES), metadata

    def evaluate_point(
        self, latitude: float, longitude: float, *, geofences: list[Geofence] | None = None, at_time: datetime | None = None
    ) -> GeofenceCheckResult:
        active_geofences = geofences if geofences is not None else self.get_geofences()[0]
        return evaluate_point_against_geofences(latitude, longitude, active_geofences, at_time=at_time)

    def nearest_hard_geofence_distance_km(
        self, latitude: float, longitude: float, *, geofences: list[Geofence] | None = None, at_time: datetime | None = None
    ) -> float | None:
        active_geofences = geofences if geofences is not None else self.get_geofences()[0]
        return nearest_hard_geofence_distance_km(latitude, longitude, active_geofences, at_time=at_time)

    # --- Static dataset status ----------------------------------------------

    def get_static_dataset_status(self, dataset_name: str) -> dict:
        """Genuinely queries the Phase 1 `static_layer_sources` registry.
        Never fabricates an "available" answer — a DB failure is reported
        as `unknown`/unreachable, not silently treated as unavailable-or-available.
        """
        cache_key = f"orca:agent:gis:dataset_status:{dataset_name}"
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            return cached

        status = self._query_dataset_status(dataset_name)
        self._cache.set_json(cache_key, status)
        return status

    def get_bathymetry_status(self) -> dict:
        return self.get_static_dataset_status("gebco_bathymetry")

    def _query_dataset_status(self, dataset_name: str) -> dict:
        try:
            from app.data.storage import list_static_layer_sources
            from app.services.database import get_engine

            rows = list_static_layer_sources(get_engine())
        except Exception as exc:  # noqa: BLE001 — DB may genuinely be unreachable (no Docker/PostGIS)
            return {
                "dataset_name": dataset_name,
                "acquisition_status": "unknown",
                "reason": f"static_layer_sources registry unreachable: {exc}",
            }

        for row in rows:
            if row.get("dataset_name") == dataset_name:
                return {
                    "dataset_name": dataset_name,
                    "acquisition_status": row.get("acquisition_status", "unknown"),
                    "is_authoritative": row.get("is_authoritative", False),
                    "processing_notes": row.get("processing_notes"),
                }

        return {"dataset_name": dataset_name, "acquisition_status": "not_acquired", "reason": "no registry row found"}


def _redis_client_or_none():
    try:
        return get_redis_client()
    except Exception:  # noqa: BLE001
        return None
