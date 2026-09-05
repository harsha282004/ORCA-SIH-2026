import pytest
from shapely.geometry import Polygon

from app.fabric.spatial import InvalidCoordinateError
from app.gis.distance import distance_to_polygon_km, haversine_km

# Known reference distance: London (51.5074, -0.1278) to Paris (48.8566, 2.3522)
# is commonly cited as ~344 km great-circle.
LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


def test_haversine_known_distance_london_paris() -> None:
    d = haversine_km(*LONDON, *PARIS)
    assert d == pytest.approx(344, abs=5)


def test_haversine_zero_distance_same_point() -> None:
    assert haversine_km(12.9, 74.8, 12.9, 74.8) == pytest.approx(0.0, abs=1e-9)


def test_haversine_symmetric() -> None:
    d1 = haversine_km(*LONDON, *PARIS)
    d2 = haversine_km(*PARIS, *LONDON)
    assert d1 == pytest.approx(d2, abs=1e-9)


def test_haversine_rejects_invalid_coordinates() -> None:
    with pytest.raises(InvalidCoordinateError):
        haversine_km(999.0, 74.8, 12.9, 74.8)


def test_haversine_one_degree_latitude_is_about_111km() -> None:
    d = haversine_km(12.0, 74.0, 13.0, 74.0)
    assert d == pytest.approx(111.19, abs=1.0)


SQUARE = Polygon([(74.0, 12.0), (74.1, 12.0), (74.1, 12.1), (74.0, 12.1), (74.0, 12.0)])


def test_point_inside_polygon_is_zero_distance() -> None:
    assert distance_to_polygon_km(12.05, 74.05, SQUARE) == 0.0


def test_point_on_polygon_boundary_is_zero_distance() -> None:
    assert distance_to_polygon_km(12.0, 74.05, SQUARE) == 0.0


def test_point_outside_polygon_has_positive_distance() -> None:
    # ~0.1 degree east of the square's eastern edge, same latitude band
    d = distance_to_polygon_km(12.05, 74.2, SQUARE)
    assert d > 0
    # roughly 0.1 degree longitude at ~12N -> ~10.9 km
    assert d == pytest.approx(10.9, abs=1.5)


def test_distance_to_polygon_rejects_empty_geometry() -> None:
    with pytest.raises(ValueError):
        distance_to_polygon_km(12.0, 74.0, Polygon())
