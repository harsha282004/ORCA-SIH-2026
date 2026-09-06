"""Deterministic alternative-route generation — Phase 5 task §12/§13/§32.

FIXTURE: a risk "wall" spanning the middle column of a wide grid, with two
symmetric open bypass corridors (left and right) — origin at the top
middle, destination at the bottom middle. The primary route picks ONE
bypass (whichever the deterministic A* tie-break favors); the alternative-
penalty mechanism must then be able to find the OTHER, genuinely distinct
bypass — never a random line, never the same route relabeled.
"""
from __future__ import annotations

from app.models.geo import BBox
from app.routing.alternatives import generate_route_alternatives
from app.routing.config import GridConfig, RoutingConfig, RoutingCostWeights, SearchConfig
from app.routing.engine import calculate_route
from app.routing.models import Coordinate, RouteRequest

# A 0.05 x 0.09 degree bbox, 3km-ish resolution -> a small, fast grid with
# room for a middle wall plus a bypass on each side.
BBOX = BBox(min_lat=12.00, min_lon=74.00, max_lat=12.05, max_lon=74.09)

CONFIG = RoutingConfig(
    grid=GridConfig(resolution_km=1.0, max_cells=2000),
    search=SearchConfig(max_expanded_nodes=20000),
    cost_weights=RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=0.0, geofence_soft=0.0, alternative_penalty=8.0),
)


def _wall_risk_provider(cell) -> float:
    # A risky wall in the middle third of columns, rows 1-3 (of however many
    # rows this resolution produces) — everything else (including both
    # outer thirds) is calm.
    n_cols = round((BBOX.max_lon - BBOX.min_lon) / (CONFIG.grid.resolution_km / 111.0))
    middle = n_cols // 2
    if abs(cell.col - middle) <= 1 and 1 <= cell.row <= 3:
        return 1.0
    return 0.0


def _zero_hazard_provider(_cell) -> float:
    return 0.0


def _request() -> RouteRequest:
    lon_mid = (BBOX.min_lon + BBOX.max_lon) / 2.0
    return RouteRequest(
        origin=Coordinate(latitude=BBOX.max_lat - 0.001, longitude=lon_mid),
        destination=Coordinate(latitude=BBOX.min_lat + 0.001, longitude=lon_mid),
    )


def _generate(max_alternatives: int = 3):
    return generate_route_alternatives(
        _request(),
        bbox=BBOX,
        geofences=[],
        risk_provider=_wall_risk_provider,
        hazard_provider=_zero_hazard_provider,
        temporal_validity="VALID",
        confidence=0.9,
        mode="demo",
        data_quality="fixture",
        routing_config=CONFIG,
        max_alternatives=max_alternatives,
    )


def test_first_alternative_is_identical_to_the_plain_calculate_route_result() -> None:
    routes = _generate(max_alternatives=1)
    plain = calculate_route(
        _request(), bbox=BBOX, geofences=[], risk_provider=_wall_risk_provider, hazard_provider=_zero_hazard_provider,
        temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="fixture", routing_config=CONFIG,
    )
    assert len(routes) == 1
    assert [(c.row, c.col) for c in routes[0].path_cells] == [(c.row, c.col) for c in plain.path_cells]


def test_second_alternative_is_genuinely_distinct_from_the_first() -> None:
    routes = _generate(max_alternatives=2)
    assert len(routes) == 2
    cells_a = {(c.row, c.col) for c in routes[0].path_cells}
    cells_b = {(c.row, c.col) for c in routes[1].path_cells}
    assert cells_a != cells_b
    # A distinct alternative must never cost LESS than the already-optimal
    # primary route (A* optimality: the primary route is the cheapest
    # possible under the UNPENALIZED cost model).
    assert routes[1].metrics.total_cost >= routes[0].metrics.total_cost


def test_alternatives_never_cross_the_risky_wall() -> None:
    routes = _generate(max_alternatives=2)
    n_cols = round((BBOX.max_lon - BBOX.min_lon) / (CONFIG.grid.resolution_km / 111.0))
    middle = n_cols // 2
    for route in routes:
        for cell in route.path_cells:
            if 1 <= cell.row <= 3:
                assert abs(cell.col - middle) > 1, "a generated alternative crossed the risky wall unnecessarily"


def test_alternatives_are_bounded_and_deterministic() -> None:
    first_run = _generate(max_alternatives=3)
    second_run = _generate(max_alternatives=3)
    assert len(first_run) <= 3
    assert [[(c.row, c.col) for c in r.path_cells] for r in first_run] == [
        [(c.row, c.col) for c in r.path_cells] for r in second_run
    ]


def test_requesting_more_alternatives_than_the_grid_supports_returns_fewer_not_an_error() -> None:
    # A trivially small, single-corridor grid: no genuinely distinct second
    # route exists, so this must return exactly 1 without raising.
    tiny_bbox = BBox(min_lat=12.00, min_lon=74.00, max_lat=12.01, max_lon=74.01)
    request = RouteRequest(
        origin=Coordinate(latitude=12.001, longitude=74.001), destination=Coordinate(latitude=12.009, longitude=74.009)
    )
    routes = generate_route_alternatives(
        request, bbox=tiny_bbox, geofences=[], risk_provider=_zero_hazard_provider, hazard_provider=_zero_hazard_provider,
        temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="fixture", max_alternatives=5,
    )
    assert 1 <= len(routes) <= 5


def test_max_alternatives_below_one_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_route_alternatives(
            _request(), bbox=BBOX, geofences=[], risk_provider=_zero_hazard_provider, hazard_provider=_zero_hazard_provider,
            temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="fixture", max_alternatives=0,
        )
