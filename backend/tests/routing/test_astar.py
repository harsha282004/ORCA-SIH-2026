"""FIXTURE A: open water. FIXTURE B: land obstacle. FIXTURE D/F: hard
geofence obstacle / no possible route. Plus corner-cutting and determinism.

All geometry here is explicit TEST FIXTURE data — never real marine or
coastline conditions.
"""
from shapely.geometry import Polygon

import pytest

from app.gis.geofence import Geofence, GeofenceCategory
from app.gis.grid import GridCell
from app.models.geo import BBox
from app.routing.astar import astar_search
from app.routing.config import RoutingCostWeights
from app.routing.errors import NoRouteFoundError
from app.routing.grid import RoutingNode, build_routing_grid, locate_cell, zero_score_provider

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)
RESOLUTION_KM = 3.0
WEIGHTS = RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0)


def build(geofences: list[Geofence]) -> dict:
    return build_routing_grid(
        BBOX, resolution_km=RESOLUTION_KM, geofences=geofences, risk_provider=zero_score_provider, hazard_provider=zero_score_provider
    )


# --- FIXTURE A: open water -------------------------------------------------


def test_fixture_a_open_water_produces_route() -> None:
    nodes = build([])
    origin_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.02, longitude=74.02)
    dest_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.28, longitude=74.28)

    result = astar_search(nodes, origin_rc, dest_rc, WEIGHTS, max_expanded_nodes=100000)

    assert result.path[0].row == origin_rc[0] and result.path[0].col == origin_rc[1]
    assert result.path[-1].row == dest_rc[0] and result.path[-1].col == dest_rc[1]
    assert result.total_cost > 0
    assert len(result.path) >= 2


def test_fixture_a_path_is_deterministic() -> None:
    nodes = build([])
    origin_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.02, longitude=74.02)
    dest_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.28, longitude=74.28)

    paths = set()
    costs = set()
    for _ in range(5):
        result = astar_search(nodes, origin_rc, dest_rc, WEIGHTS, max_expanded_nodes=100000)
        paths.add(tuple((n.row, n.col) for n in result.path))
        costs.add(round(result.total_cost, 9))

    assert len(paths) == 1
    assert len(costs) == 1


# --- FIXTURE B: land obstacle in the middle --------------------------------


def test_fixture_b_routes_around_land_obstacle() -> None:
    # A block in the middle of the bbox that does NOT span the full
    # latitude range — it leaves a gap at both the north and south edges
    # for A* to route around (a full-height block would just partition the
    # domain, which is exercised separately by FIXTURE D/F below).
    land = Geofence(
        id="land-mid",
        name="land-mid",
        category=GeofenceCategory.LAND,
        is_authoritative=False,
        source="fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [[[74.1, 12.08], [74.2, 12.08], [74.2, 12.22], [74.1, 12.22], [74.1, 12.08]]],
        },
    )
    nodes = build([land])
    origin_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.15, longitude=74.02)
    dest_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.15, longitude=74.28)

    result = astar_search(nodes, origin_rc, dest_rc, WEIGHTS, max_expanded_nodes=100000)

    for node in result.path:
        assert node.navigable
        assert (node.row, node.col) not in {(n.row, n.col) for n in nodes.values() if not n.navigable}


# --- FIXTURE D/F: hard geofence fully partitions the domain ---------------


def test_fixture_d_full_width_hard_geofence_blocks_route() -> None:
    wall = Geofence(
        id="wall",
        name="wall",
        category=GeofenceCategory.PROTECTED_AREA,
        is_authoritative=True,
        source="fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [[[74.0, 12.14], [74.3, 12.14], [74.3, 12.16], [74.0, 12.16], [74.0, 12.14]]],
        },
    )
    nodes = build([wall])
    origin_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.02, longitude=74.15)
    dest_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.28, longitude=74.15)

    with pytest.raises(NoRouteFoundError) as exc_info:
        astar_search(nodes, origin_rc, dest_rc, WEIGHTS, max_expanded_nodes=100000)
    assert exc_info.value.expanded_nodes > 0


def test_no_route_never_returns_partial_path() -> None:
    # The only assertion that matters here: a NoRouteFoundError is raised,
    # never a truncated/partial AStarResult — there is no code path in
    # astar_search that returns anything on failure other than raising.
    wall = Geofence(
        id="wall2",
        name="wall2",
        category=GeofenceCategory.LAND,
        is_authoritative=False,
        source="fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [[[74.0, 12.14], [74.3, 12.14], [74.3, 12.16], [74.0, 12.16], [74.0, 12.14]]],
        },
    )
    nodes = build([wall])
    origin_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.02, longitude=74.15)
    dest_rc = locate_cell(BBOX, resolution_km=RESOLUTION_KM, latitude=12.28, longitude=74.15)
    with pytest.raises(NoRouteFoundError):
        astar_search(nodes, origin_rc, dest_rc, WEIGHTS, max_expanded_nodes=100000)


# --- Corner-cutting prevention ---------------------------------------------


def _cell(row: int, col: int, navigable: bool) -> RoutingNode:
    geometry = Polygon([(74.0 + col * 0.01, 12.0 + row * 0.01), (74.01 + col * 0.01, 12.0 + row * 0.01),
                         (74.01 + col * 0.01, 12.01 + row * 0.01), (74.0 + col * 0.01, 12.01 + row * 0.01)])
    cell = GridCell(
        cell_id=f"r{row}c{col}", row=row, col=col, geometry=geometry,
        centroid_lat=12.005 + row * 0.01, centroid_lon=74.005 + col * 0.01,
    )
    return RoutingNode(cell=cell, navigable=navigable)


def test_corner_cutting_is_prevented() -> None:
    # 4x4 grid, all navigable except (1,2) and (2,1) — the two orthogonal
    # cells adjacent to the diagonal move from origin (1,1) to destination
    # (2,2). That diagonal must be rejected; a longer path around the
    # blocked pair (e.g. via row 0 and column 3) must still exist and be
    # what A* actually returns.
    nodes = {(r, c): _cell(r, c, True) for r in range(4) for c in range(4)}
    nodes[(1, 2)] = _cell(1, 2, False)
    nodes[(2, 1)] = _cell(2, 1, False)

    result = astar_search(nodes, (1, 1), (2, 2), WEIGHTS, max_expanded_nodes=1000)

    path_rc = [(n.row, n.col) for n in result.path]
    assert path_rc[0] == (1, 1)
    assert path_rc[-1] == (2, 2)
    assert len(path_rc) > 2, "a direct corner-cut diagonal step was taken, which must be forbidden"
    # The direct diagonal step must never appear consecutively in the path.
    for prev, curr in zip(path_rc, path_rc[1:]):
        if prev == (1, 1) and curr == (2, 2):
            pytest.fail("corner-cut diagonal (1,1)->(2,2) was taken directly")


def test_corner_cutting_allowed_when_both_orthogonals_open() -> None:
    nodes = {
        (0, 0): _cell(0, 0, True),
        (0, 1): _cell(0, 1, True),
        (1, 0): _cell(1, 0, True),
        (1, 1): _cell(1, 1, True),
    }
    result = astar_search(nodes, (0, 0), (1, 1), WEIGHTS, max_expanded_nodes=1000)
    path_rc = [(n.row, n.col) for n in result.path]
    assert path_rc == [(0, 0), (1, 1)]  # direct diagonal is fine when not corner-cutting
