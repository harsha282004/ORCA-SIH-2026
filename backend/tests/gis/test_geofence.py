from datetime import datetime, timedelta, timezone

import pytest

from app.gis.geofence import (
    ConstraintType,
    Geofence,
    GeofenceCategory,
    evaluate_point_against_geofences,
    nearest_hard_geofence_distance_km,
)

LAND_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[74.80, 12.80], [74.90, 12.80], [74.90, 12.90], [74.80, 12.90], [74.80, 12.80]]],
}

MPA_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[74.30, 13.00], [74.35, 13.00], [74.35, 13.05], [74.30, 13.05], [74.30, 13.00]]],
}


def make_land() -> Geofence:
    return Geofence(
        id="land-1",
        name="Coastal fixture land mass",
        category=GeofenceCategory.LAND,
        geometry=LAND_GEOJSON,
        is_authoritative=True,
        source="fixture",
    )


def make_mpa(active_from=None, active_to=None) -> Geofence:
    return Geofence(
        id="mpa-1",
        name="Fixture protected area",
        category=GeofenceCategory.PROTECTED_AREA,
        geometry=MPA_GEOJSON,
        is_authoritative=True,
        source="fixture",
        active_from=active_from,
        active_to=active_to,
    )


def test_point_outside_all_geofences_is_allowed() -> None:
    result = evaluate_point_against_geofences(13.075, 74.275, [make_land(), make_mpa()])
    assert result.allowed is True
    assert result.blocked is False


def test_point_inside_hard_geofence_is_blocked() -> None:
    result = evaluate_point_against_geofences(12.85, 74.85, [make_land()])
    assert result.allowed is False
    assert result.blocked is True
    assert result.constraint_type == ConstraintType.HARD
    assert result.matched_geofence_id == "land-1"
    assert result.is_authoritative is True


def test_point_on_geofence_boundary_is_blocked() -> None:
    # Exactly on the western edge of the land fixture square.
    result = evaluate_point_against_geofences(12.85, 74.80, [make_land()])
    assert result.blocked is True


def test_inactive_time_bound_geofence_does_not_block() -> None:
    # Verifies activity windows (architecture.md §25 "time-dependent
    # restrictions") are actually respected, not just always-on.
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    expired_zone = make_mpa(active_from=now - timedelta(days=10), active_to=now - timedelta(days=1))
    result = evaluate_point_against_geofences(13.02, 74.32, [expired_zone], at_time=now)
    assert result.allowed is True


def test_active_time_bound_geofence_blocks() -> None:
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    active_zone = make_mpa(active_from=now - timedelta(days=1), active_to=now + timedelta(days=1))
    result = evaluate_point_against_geofences(13.02, 74.32, [active_zone], at_time=now)
    assert result.blocked is True


def test_nearest_hard_geofence_distance_positive_outside() -> None:
    d = nearest_hard_geofence_distance_km(13.075, 74.275, [make_land()])
    assert d is not None
    assert d > 0


def test_nearest_hard_geofence_distance_none_when_no_hard_geofences() -> None:
    d = nearest_hard_geofence_distance_km(13.075, 74.275, [])
    assert d is None


def test_geofence_rejects_malformed_geometry() -> None:
    with pytest.raises(Exception):
        Geofence(
            id="bad",
            name="bad",
            category=GeofenceCategory.LAND,
            geometry={"type": "Polygon", "coordinates": "not-a-list"},
            is_authoritative=True,
            source="fixture",
        )
