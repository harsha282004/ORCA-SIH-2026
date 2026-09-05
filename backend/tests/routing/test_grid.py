from app.gis.geofence import Geofence, GeofenceCategory
from app.models.geo import BBox
from app.routing.grid import build_routing_grid, locate_cell, zero_score_provider

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)
RESOLUTION_KM = 3.0


def test_build_routing_grid_all_navigable_when_no_geofences() -> None:
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    assert len(nodes) > 0
    assert all(n.navigable for n in nodes.values())


def test_build_routing_grid_blocks_land_cells() -> None:
    land = Geofence(
        id="land",
        name="land",
        category=GeofenceCategory.LAND,
        is_authoritative=False,
        source="fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [[[74.0, 12.0], [74.1, 12.0], [74.1, 12.1], [74.0, 12.1], [74.0, 12.0]]],
        },
    )
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[land], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    blocked = [n for n in nodes.values() if not n.navigable]
    navigable = [n for n in nodes.values() if n.navigable]
    assert len(blocked) > 0
    assert len(navigable) > 0
    for node in blocked:
        assert node.block_reason is not None


def test_build_routing_grid_catches_obstacle_thinner_than_one_cell() -> None:
    """Regression test for the centroid-only masking bug found during
    Phase 3 development: a hard geofence thinner than one grid cell must
    still block that cell, not fall silently between two centroids.
    """
    # ~2.2km thick band (0.02 deg lat), thinner than the ~3km grid resolution.
    thin_wall = Geofence(
        id="thin-wall",
        name="thin-wall",
        category=GeofenceCategory.LAND,
        is_authoritative=False,
        source="fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [[[74.0, 12.14], [74.3, 12.14], [74.3, 12.16], [74.0, 12.16], [74.0, 12.14]]],
        },
    )
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[thin_wall], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    blocked_rows = {n.row for n in nodes.values() if not n.navigable}
    assert len(blocked_rows) > 0, "a hard geofence thinner than one cell must still block at least one row"


def test_navigable_cells_have_geofence_soft_penalty_field() -> None:
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    for node in nodes.values():
        assert 0.0 <= node.geofence_soft_penalty <= 1.0


def test_locate_cell_within_bounds() -> None:
    row, col = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.15, longitude=74.15)
    assert row >= 0
    assert col >= 0


def test_locate_cell_clamps_to_grid_edges() -> None:
    # exactly on the max boundary — must clamp into the last row/col, not overflow
    row, col = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=BBOX.max_lat, longitude=BBOX.max_lon)
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    assert (row, col) in nodes


def test_locate_cell_is_consistent_with_grid_cell_bounds() -> None:
    nodes = build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=[], risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )
    for node in nodes.values():
        row, col = locate_cell(
            BBOX, resolution_km=RESOLUTION_KM, latitude=node.cell.centroid_lat, longitude=node.cell.centroid_lon
        )
        assert (row, col) == (node.row, node.col)
