from datetime import datetime, timezone

import pytest

from app.agents.common.cache import AgentCache
from app.agents.gis.agent import GISGeofencingAgent
from app.fabric.spatial import InvalidCoordinateError
from app.gis.geofence import Geofence, GeofenceCategory
from app.models.geo import BBox

PROTECTED_AREA = Geofence(
    id="mpa-1",
    name="Test protected area",
    category=GeofenceCategory.PROTECTED_AREA,
    is_authoritative=True,
    source="fixture",
    geometry={
        "type": "Polygon",
        "coordinates": [[[74.30, 13.00], [74.35, 13.00], [74.35, 13.05], [74.30, 13.05], [74.30, 13.00]]],
    },
)


def make_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent(cache=AgentCache(None, ttl_seconds=60))


def test_validate_coordinate_accepts_valid_point() -> None:
    make_agent().validate_coordinate(12.9, 74.8)  # must not raise


def test_validate_coordinate_rejects_invalid_point() -> None:
    with pytest.raises(InvalidCoordinateError):
        make_agent().validate_coordinate(999.0, 74.8)


def test_get_geofences_returns_labeled_fixture_metadata() -> None:
    agent = make_agent()
    geofences, metadata = agent.get_geofences()

    assert len(geofences) >= 1
    assert metadata["is_authoritative"] is False
    assert metadata["source_tier"] == "synthetic"
    assert "DEMO DATA" in metadata["disclaimer"]


def test_evaluate_point_hard_geofence_land() -> None:
    agent = make_agent()
    geofences, _ = agent.get_geofences()
    # A point inside the demo land fixture (12.70-13.45 lat, 74.80-75.05 lon).
    result = agent.evaluate_point(13.0, 74.9, geofences=geofences)
    assert result.blocked is True
    assert result.constraint_type.value == "hard"


def test_evaluate_point_open_water_not_blocked() -> None:
    agent = make_agent()
    geofences, _ = agent.get_geofences()
    result = agent.evaluate_point(12.80, 74.20, geofences=geofences)
    assert result.allowed is True


def test_evaluate_point_protected_area_blocks() -> None:
    agent = make_agent()
    result = agent.evaluate_point(13.02, 74.32, geofences=[PROTECTED_AREA])
    assert result.blocked is True


def test_evaluate_point_respects_time_window() -> None:
    agent = make_agent()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    expired_zone = Geofence(
        id="rz-1", name="rz", category=GeofenceCategory.RESTRICTED_ZONE, is_authoritative=True, source="fixture",
        geometry=PROTECTED_AREA.geometry, active_from=datetime(2020, 1, 1, tzinfo=timezone.utc), active_to=datetime(2021, 1, 1, tzinfo=timezone.utc),
    )
    result = agent.evaluate_point(13.02, 74.32, geofences=[expired_zone], at_time=now)
    assert result.allowed is True  # zone's active window has long since passed


def test_nearest_hard_geofence_distance_returns_positive_when_outside() -> None:
    agent = make_agent()
    distance = agent.nearest_hard_geofence_distance_km(12.80, 74.20, geofences=[PROTECTED_AREA])
    assert distance is not None
    assert distance > 0


def test_nearest_hard_geofence_distance_none_without_hard_geofences() -> None:
    agent = make_agent()
    assert agent.nearest_hard_geofence_distance_km(12.80, 74.20, geofences=[]) is None


def test_distance_km_matches_haversine() -> None:
    from app.gis.distance import haversine_km

    agent = make_agent()
    assert agent.distance_km(12.0, 74.0, 12.1, 74.1) == haversine_km(12.0, 74.0, 12.1, 74.1)


def test_generate_candidate_grid_delegates_to_gis_grid() -> None:
    agent = make_agent()
    bbox = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.1, max_lon=74.1)
    cells = agent.generate_candidate_grid(bbox, resolution_km=5.0)
    assert len(cells) > 0


def test_static_dataset_status_unreachable_db_reports_unknown_not_available() -> None:
    """We don't have a live PostGIS instance in this test environment —
    this proves the agent reports honest uncertainty rather than
    fabricating "available" or silently assuming "not_acquired" without
    checking.
    """
    agent = make_agent()
    status = agent.get_static_dataset_status("gebco_bathymetry")
    assert status["dataset_name"] == "gebco_bathymetry"
    assert status["acquisition_status"] in ("unknown", "not_acquired")  # never "available" here


def test_bathymetry_status_never_fabricates_available() -> None:
    agent = make_agent()
    status = agent.get_bathymetry_status()
    assert status["acquisition_status"] != "available"


def test_static_dataset_status_is_cached(fake_redis) -> None:
    agent = GISGeofencingAgent(cache=AgentCache(fake_redis, ttl_seconds=60))
    status1 = agent.get_static_dataset_status("gebco_bathymetry")
    status2 = agent.get_static_dataset_status("gebco_bathymetry")
    assert status1 == status2
    assert len(fake_redis.store) == 1
