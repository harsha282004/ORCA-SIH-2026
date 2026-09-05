import pytest
from shapely.geometry import Polygon

from app.gis.geometry import CRS, InvalidGeometryError, polygon_from_geojson, validate_polygon
from app.fabric.spatial import InvalidCoordinateError, validate_point

SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[74.0, 12.0], [74.1, 12.0], [74.1, 12.1], [74.0, 12.1], [74.0, 12.0]]],
}

# A classic "bowtie" self-intersecting polygon — geometrically invalid.
BOWTIE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
}


def test_crs_is_epsg4326() -> None:
    assert CRS == "EPSG:4326"


def test_valid_point_reused_from_fabric() -> None:
    validate_point(12.9, 74.8)  # must not raise


def test_invalid_point_raises() -> None:
    with pytest.raises(InvalidCoordinateError):
        validate_point(999.0, 74.8)


def test_valid_polygon_from_geojson() -> None:
    polygon = polygon_from_geojson(SQUARE_GEOJSON)
    result = validate_polygon(polygon)
    assert result.was_repaired is False
    assert result.original_valid is True
    assert isinstance(result.geometry, Polygon)


def test_malformed_geojson_raises() -> None:
    with pytest.raises(InvalidGeometryError):
        polygon_from_geojson({"type": "Polygon", "coordinates": "not-a-list"})


def test_wrong_geometry_type_raises() -> None:
    point_geojson = {"type": "Point", "coordinates": [74.0, 12.0]}
    with pytest.raises(InvalidGeometryError):
        polygon_from_geojson(point_geojson)


def test_empty_geometry_raises() -> None:
    empty_polygon = Polygon()
    with pytest.raises(InvalidGeometryError):
        validate_polygon(empty_polygon)


def test_invalid_geometry_raises_without_repair() -> None:
    # polygon_from_geojson only rejects structurally malformed input, not
    # geometrically invalid (self-intersecting) polygons — Shapely
    # constructs the bowtie fine, it's just .is_valid == False, which is
    # validate_polygon's job to catch.
    bowtie = polygon_from_geojson(BOWTIE_GEOJSON)
    with pytest.raises(InvalidGeometryError):
        validate_polygon(bowtie, repair=False)


def test_invalid_geometry_can_be_explicitly_repaired() -> None:
    bowtie = polygon_from_geojson(BOWTIE_GEOJSON)
    result = validate_polygon(bowtie, repair=True)
    assert result.was_repaired is True
    assert result.original_valid is False
    assert result.geometry.is_valid
