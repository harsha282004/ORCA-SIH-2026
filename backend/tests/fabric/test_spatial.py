import pytest

from app.fabric.spatial import CRS, InvalidCoordinateError, point_in_bbox, validate_point
from app.models.geo import BBox


def test_crs_is_epsg4326() -> None:
    assert CRS == "EPSG:4326"


def test_valid_point_passes() -> None:
    validate_point(12.91, 74.79)  # must not raise


@pytest.mark.parametrize("lat,lon", [(None, 74.0), (12.0, None), (91.0, 74.0), (-91.0, 74.0)])
def test_invalid_latitude_rejected(lat, lon) -> None:
    with pytest.raises(InvalidCoordinateError):
        validate_point(lat, lon)


@pytest.mark.parametrize("lat,lon", [(12.0, 181.0), (12.0, -181.0)])
def test_invalid_longitude_rejected(lat, lon) -> None:
    with pytest.raises(InvalidCoordinateError):
        validate_point(lat, lon)


def test_point_in_bbox() -> None:
    bbox = BBox(min_lat=12.0, min_lon=74.0, max_lat=13.0, max_lon=75.0)
    assert point_in_bbox(12.5, 74.5, bbox)
    assert not point_in_bbox(20.0, 74.5, bbox)


def test_bbox_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        BBox(min_lat=13.0, min_lon=74.0, max_lat=12.0, max_lon=75.0)
