"""FIXTURE C: two corridors, one shorter-but-risky, one longer-but-safer.

This proves the route engine can select the lower TOTAL-COST route rather
than blindly choosing the shortest geometric path — under ORCA's
configured cost model, not as a claim about universal maritime safety.

All grids here are hand-built synthetic fixtures with an explicit,
reasoned-through cost comparison — never real marine conditions.
"""
from shapely.geometry import Polygon

from app.gis.grid import GridCell
from app.routing.astar import astar_search
from app.routing.config import RoutingCostWeights
from app.routing.grid import RoutingNode

WEIGHTS = RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0)


def make_grid(risk_by_rc: dict, hazard_by_rc: dict, size: int = 5) -> dict:
    nodes = {}
    for row in range(size):
        for col in range(size):
            geometry = Polygon(
                [
                    (74.0 + col * 0.01, 12.0 + row * 0.01),
                    (74.01 + col * 0.01, 12.0 + row * 0.01),
                    (74.01 + col * 0.01, 12.01 + row * 0.01),
                    (74.0 + col * 0.01, 12.01 + row * 0.01),
                ]
            )
            cell = GridCell(
                cell_id=f"r{row}c{col}",
                row=row,
                col=col,
                geometry=geometry,
                centroid_lat=12.005 + row * 0.01,
                centroid_lon=74.005 + col * 0.01,
            )
            nodes[(row, col)] = RoutingNode(
                cell=cell,
                navigable=True,
                risk_score=risk_by_rc.get((row, col), 0.0),
                hazard_score=hazard_by_rc.get((row, col), 0.0),
            )
    return nodes


def test_risk_aware_routing_prefers_lower_total_cost_over_shortest_path() -> None:
    # A high-risk wall straight down the middle column (rows 1-3), origin
    # at top-middle, destination at bottom-middle. The direct path crosses
    # 3 risky cells; a detour via the edge columns crosses none.
    risky = {(1, 2): 1.0, (2, 2): 1.0, (3, 2): 1.0}
    nodes = make_grid(risky, {})

    result = astar_search(nodes, (0, 2), (4, 2), WEIGHTS, max_expanded_nodes=10000)
    path_rc = [(n.row, n.col) for n in result.path]

    assert (1, 2) not in path_rc
    assert (2, 2) not in path_rc
    assert (3, 2) not in path_rc
    assert path_rc[0] == (0, 2)
    assert path_rc[-1] == (4, 2)


def test_risk_aware_routing_accepts_direct_path_when_cheaper() -> None:
    # Same geometry, but risk weight effectively neutralized by a tiny risk
    # value — the shortest (direct) path should now win, proving the
    # engine isn't just always avoiding the middle column unconditionally.
    tiny_risk = {(1, 2): 0.001, (2, 2): 0.001, (3, 2): 0.001}
    nodes = make_grid(tiny_risk, {})

    result = astar_search(nodes, (0, 2), (4, 2), WEIGHTS, max_expanded_nodes=10000)
    path_rc = [(n.row, n.col) for n in result.path]

    assert path_rc == [(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)]


def test_hazard_aware_routing_avoids_hazardous_corridor() -> None:
    # Same shape as the risk test, but purely via hazard_score, to prove
    # hazard cost independently influences route selection (Phase 3 task
    # spec §40) — it is not derived from risk_score.
    hazardous = {(1, 2): 1.0, (2, 2): 1.0, (3, 2): 1.0}
    nodes = make_grid({}, hazardous)

    result = astar_search(nodes, (0, 2), (4, 2), WEIGHTS, max_expanded_nodes=10000)
    path_rc = [(n.row, n.col) for n in result.path]

    assert (1, 2) not in path_rc
    assert (2, 2) not in path_rc
    assert (3, 2) not in path_rc


def test_hazard_does_not_hard_block_only_costs_more() -> None:
    # A single very hazardous cell that is nonetheless still `navigable` —
    # hazard alone must never make a cell impassable; only the Safety/
    # Geofence policy (hard geofences) may do that (Phase 3 task spec §40).
    hazardous = {(2, 2): 1.0}
    nodes = make_grid({}, hazardous)
    assert nodes[(2, 2)].navigable is True

    # Force a 1-wide corridor through (2,2): every other cell in row 2 is
    # blocked, so a route from row 0 to row 4 has no choice but to cross
    # the hazardous cell — proving it's traversable (costly, not blocked).
    for col in range(5):
        if col != 2:
            nodes[(2, col)] = nodes[(2, col)].model_copy(update={"navigable": False})

    result = astar_search(nodes, (0, 2), (4, 2), WEIGHTS, max_expanded_nodes=10000)
    path_rc = [(n.row, n.col) for n in result.path]
    assert (2, 2) in path_rc  # forced through the only open cell, despite its hazard cost
