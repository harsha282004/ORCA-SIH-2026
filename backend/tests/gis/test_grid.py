import pytest

from app.gis.grid import generate_grid
from app.models.geo import BBox

SMALL_BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.1, max_lon=74.1)  # ~11km x 10.9km


def test_generate_grid_produces_cells() -> None:
    cells = generate_grid(SMALL_BBOX, resolution_km=5.0)
    assert len(cells) > 0


def test_generate_grid_is_deterministic() -> None:
    cells1 = generate_grid(SMALL_BBOX, resolution_km=3.0)
    cells2 = generate_grid(SMALL_BBOX, resolution_km=3.0)
    assert [c.cell_id for c in cells1] == [c.cell_id for c in cells2]
    for c1, c2 in zip(cells1, cells2):
        assert c1.geometry.equals(c2.geometry)


def test_generate_grid_cells_cover_bbox_centroid_within_bounds() -> None:
    cells = generate_grid(SMALL_BBOX, resolution_km=3.0)
    for cell in cells:
        assert SMALL_BBOX.min_lat <= cell.centroid_lat <= SMALL_BBOX.max_lat
        assert SMALL_BBOX.min_lon <= cell.centroid_lon <= SMALL_BBOX.max_lon


def test_finer_resolution_produces_more_cells() -> None:
    coarse = generate_grid(SMALL_BBOX, resolution_km=10.0)
    fine = generate_grid(SMALL_BBOX, resolution_km=2.0)
    assert len(fine) > len(coarse)


def test_generate_grid_rejects_non_positive_resolution() -> None:
    with pytest.raises(ValueError):
        generate_grid(SMALL_BBOX, resolution_km=0)
    with pytest.raises(ValueError):
        generate_grid(SMALL_BBOX, resolution_km=-1.0)


def test_cell_geojson_shape() -> None:
    cells = generate_grid(SMALL_BBOX, resolution_km=5.0)
    geojson = cells[0].to_geojson()
    assert geojson["type"] == "Feature"
    assert geojson["geometry"]["type"] == "Polygon"
