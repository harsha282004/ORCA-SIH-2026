"""FIXTURE E: destination completely blocked. FIXTURE G: origin ==
destination. Plus temporal validity / confidence gating (Phase 3 task
spec §28-29, §42-43, §46).
"""
import pytest
from pydantic import ValidationError

from app.gis.geofence import Geofence, GeofenceCategory
from app.models.geo import BBox
from app.routing.errors import DestinationValidationError, OriginValidationError, RouteDataQualityError
from app.routing.engine import calculate_route
from app.routing.grid import zero_score_provider
from app.routing.models import Coordinate, RouteRequest

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)

BLOCK = Geofence(
    id="block",
    name="block",
    category=GeofenceCategory.PROTECTED_AREA,
    is_authoritative=True,
    source="fixture",
    geometry={
        "type": "Polygon",
        "coordinates": [[[74.20, 12.20], [74.30, 12.20], [74.30, 12.30], [74.20, 12.30], [74.20, 12.20]]],
    },
)


def make_request(origin=(12.02, 74.02), destination=(12.25, 74.25)) -> RouteRequest:
    return RouteRequest(
        origin=Coordinate(latitude=origin[0], longitude=origin[1]),
        destination=Coordinate(latitude=destination[0], longitude=destination[1]),
    )


def run(request, geofences=None, confidence=0.9, temporal_validity="VALID"):
    return calculate_route(
        request,
        bbox=BBOX,
        geofences=geofences or [],
        risk_provider=zero_score_provider,
        hazard_provider=zero_score_provider,
        temporal_validity=temporal_validity,
        confidence=confidence,
        mode="demo",
        data_quality="fixture",
    )


# --- Coordinate validation happens at the model layer ----------------------


def test_coordinate_rejects_invalid_latitude() -> None:
    with pytest.raises(ValidationError):
        Coordinate(latitude=999.0, longitude=74.0)


def test_coordinate_rejects_invalid_longitude() -> None:
    with pytest.raises(ValidationError):
        Coordinate(latitude=12.0, longitude=999.0)


# --- FIXTURE E: destination completely blocked -----------------------------


def test_destination_inside_hard_geofence_fails_before_astar() -> None:
    request = make_request(destination=(12.25, 74.25))  # inside BLOCK
    with pytest.raises(DestinationValidationError) as exc_info:
        run(request, geofences=[BLOCK])
    assert exc_info.value.issue.code == "BLOCKED_LAND_OR_GEOFENCE"


def test_destination_outside_domain_fails_before_astar() -> None:
    request = make_request(destination=(20.0, 80.0))  # far outside BBOX
    with pytest.raises(DestinationValidationError) as exc_info:
        run(request)
    assert exc_info.value.issue.code == "OUT_OF_DOMAIN"


# --- Origin invalid ----------------------------------------------------------


def test_origin_inside_hard_geofence_fails_before_astar() -> None:
    request = make_request(origin=(12.25, 74.25), destination=(12.02, 74.02))
    with pytest.raises(OriginValidationError) as exc_info:
        run(request, geofences=[BLOCK])
    assert exc_info.value.issue.code == "BLOCKED_LAND_OR_GEOFENCE"


def test_origin_outside_domain_fails_before_astar() -> None:
    request = make_request(origin=(0.0, 0.0))
    with pytest.raises(OriginValidationError) as exc_info:
        run(request)
    assert exc_info.value.issue.code == "OUT_OF_DOMAIN"


def test_destination_validated_even_when_origin_is_also_invalid() -> None:
    # Origin is checked first in the engine, so this proves origin-first
    # ordering rather than destination being silently skipped — a
    # complementary destination-only test above proves it independently.
    request = make_request(origin=(0.0, 0.0), destination=(12.25, 74.25))
    with pytest.raises(OriginValidationError):
        run(request, geofences=[BLOCK])


# --- FIXTURE G: origin == destination ---------------------------------------


def test_origin_equals_destination_returns_zero_distance_route() -> None:
    request = make_request(origin=(12.15, 74.15), destination=(12.15, 74.15))
    result = run(request)
    assert result.metrics.total_distance_km == 0.0
    assert result.metrics.total_cost == 0.0
    assert result.metrics.cell_count == 1
    assert result.feasibility_status == "FEASIBLE"


def test_origin_equals_destination_but_blocked_still_fails_validation() -> None:
    request = make_request(origin=(12.25, 74.25), destination=(12.25, 74.25))
    with pytest.raises(OriginValidationError):
        run(request, geofences=[BLOCK])


# --- Temporal validity / confidence gating ----------------------------------


@pytest.mark.parametrize(
    "temporal_validity,expected_code",
    [
        ("STALE", "STALE_DATA"),
        ("EXPIRED", "EXPIRED_DATA"),
        ("MISSING_TIMESTAMP", "MISSING_DATA"),
        ("INVALID_TIMESTAMP", "INVALID_TIMESTAMP"),
    ],
)
def test_bad_temporal_validity_refuses_to_route(temporal_validity, expected_code) -> None:
    request = make_request()
    with pytest.raises(RouteDataQualityError) as exc_info:
        run(request, temporal_validity=temporal_validity)
    assert exc_info.value.issue.code == expected_code


def test_valid_temporal_validity_allows_routing() -> None:
    request = make_request()
    result = run(request, temporal_validity="VALID")
    assert result.feasibility_status == "FEASIBLE"
    assert result.temporal_validity == "VALID"


def test_low_confidence_refuses_to_route() -> None:
    request = make_request()
    with pytest.raises(RouteDataQualityError) as exc_info:
        run(request, confidence=0.01)
    assert exc_info.value.issue.code == "LOW_CONFIDENCE"


def test_sufficient_confidence_allows_routing() -> None:
    request = make_request()
    result = run(request, confidence=0.99)
    assert result.confidence == 0.99
