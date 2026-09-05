"""Deterministic A* search — architecture.md §26 ("A* (Haversine heuristic)").

Design choices, each deliberate and documented (Phase 3 task spec §13-15):

- **8-neighbor movement**, with corner-cutting explicitly prevented: a
  diagonal move between (r, c) and (r+dr, c+dc) is only legal if BOTH
  orthogonal cells (r+dr, c) and (r, c+dc) are also navigable. Two blocked
  orthogonal neighbors form a solid corner that a diagonal move must not
  cut through — this is what stops a route from visually clipping the
  corner of a land mass or hard geofence.
- **Heuristic = geographic distance only**, scaled by the same
  `cost_weights.distance` coefficient the edge cost uses. Environmental
  risk/hazard/geofence costs are all >= 0, so the true edge cost is always
  >= `weights.distance * haversine_km(...)` — the heuristic remains an
  admissible lower bound regardless of how risky/hazardous the actual path
  turns out to be. Folding risk into the heuristic itself was deliberately
  avoided (per the Phase 3 task spec's explicit instruction) because doing
  so cannot be proven admissible without knowing the least-risky-per-km
  value across the whole grid in advance.
- **Deterministic tie-breaking**: every heap entry carries a strictly
  increasing insertion counter as its second sort key, so ties in f-score
  are always broken in insertion (FIFO) order — never by Python's
  incidental dict/set iteration order, and never randomly.
"""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from app.gis.distance import haversine_km
from app.routing.config import RoutingCostWeights
from app.routing.costs import EdgeCostBreakdown, compute_edge_cost
from app.routing.errors import NoRouteFoundError, RoutingResourceLimitError
from app.routing.grid import RoutingNode

RC = tuple[int, int]

_DIAGONAL_DELTAS = {(-1, -1), (-1, 1), (1, -1), (1, 1)}
_ALL_DELTAS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass
class AStarResult:
    path: list[RoutingNode]
    edge_costs: list[EdgeCostBreakdown]  # one per consecutive pair in `path`, len == len(path) - 1
    total_cost: float
    expanded_nodes: int


def _neighbors(rc: RC, nodes: dict[RC, RoutingNode]):
    row, col = rc
    for dr, dc in _ALL_DELTAS:
        neighbor_rc = (row + dr, col + dc)
        neighbor = nodes.get(neighbor_rc)
        if neighbor is None or not neighbor.navigable:
            continue

        if (dr, dc) in _DIAGONAL_DELTAS:
            # Corner-cutting prevention: both orthogonal cells adjacent to
            # this diagonal move must also be navigable.
            ortho_a = nodes.get((row + dr, col))
            ortho_b = nodes.get((row, col + dc))
            if ortho_a is None or not ortho_a.navigable:
                continue
            if ortho_b is None or not ortho_b.navigable:
                continue

        yield neighbor_rc, neighbor


def astar_search(
    nodes: dict[RC, RoutingNode],
    origin_rc: RC,
    destination_rc: RC,
    weights: RoutingCostWeights,
    *,
    max_expanded_nodes: int,
) -> AStarResult:
    if origin_rc not in nodes:
        raise ValueError(f"origin cell {origin_rc} is not in the grid")
    if destination_rc not in nodes:
        raise ValueError(f"destination cell {destination_rc} is not in the grid")

    destination_node = nodes[destination_rc]

    def heuristic(rc: RC) -> float:
        node = nodes[rc]
        return weights.distance * haversine_km(
            node.cell.centroid_lat, node.cell.centroid_lon, destination_node.cell.centroid_lat, destination_node.cell.centroid_lon
        )

    counter = itertools.count()
    open_heap: list[tuple[float, int, RC]] = [(heuristic(origin_rc), next(counter), origin_rc)]
    g_score: dict[RC, float] = {origin_rc: 0.0}
    came_from: dict[RC, tuple[RC, EdgeCostBreakdown]] = {}
    closed: set[RC] = set()
    expanded = 0

    while open_heap:
        _, _, current_rc = heapq.heappop(open_heap)
        if current_rc in closed:
            continue

        expanded += 1
        if expanded > max_expanded_nodes:
            raise RoutingResourceLimitError(
                f"A* search exceeded the configured max_expanded_nodes={max_expanded_nodes} "
                "without reaching the destination"
            )

        if current_rc == destination_rc:
            return _reconstruct(came_from, origin_rc, destination_rc, nodes, g_score[current_rc], expanded)

        closed.add(current_rc)
        current_node = nodes[current_rc]

        for neighbor_rc, neighbor_node in _neighbors(current_rc, nodes):
            if neighbor_rc in closed:
                continue

            edge = compute_edge_cost(current_node, neighbor_node, weights)
            tentative_g = g_score[current_rc] + edge.total

            if tentative_g < g_score.get(neighbor_rc, math.inf):
                g_score[neighbor_rc] = tentative_g
                came_from[neighbor_rc] = (current_rc, edge)
                f_score = tentative_g + heuristic(neighbor_rc)
                heapq.heappush(open_heap, (f_score, next(counter), neighbor_rc))

    raise NoRouteFoundError(
        f"no navigable path exists between {origin_rc} and {destination_rc}", expanded_nodes=expanded
    )


def _reconstruct(
    came_from: dict[RC, tuple[RC, EdgeCostBreakdown]],
    origin_rc: RC,
    destination_rc: RC,
    nodes: dict[RC, RoutingNode],
    total_cost: float,
    expanded_nodes: int,
) -> AStarResult:
    path_rc: list[RC] = [destination_rc]
    edges: list[EdgeCostBreakdown] = []

    current = destination_rc
    while current != origin_rc:
        current, edge = came_from[current]
        path_rc.append(current)
        edges.append(edge)

    path_rc.reverse()
    edges.reverse()

    path = [nodes[rc] for rc in path_rc]
    return AStarResult(path=path, edge_costs=edges, total_cost=total_cost, expanded_nodes=expanded_nodes)
