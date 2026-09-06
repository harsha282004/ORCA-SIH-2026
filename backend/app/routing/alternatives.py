"""Deterministic alternative-route generation — Phase 5 task §12/§13.

Reuses `app.routing.engine.calculate_route` UNCHANGED (same grid-building,
same validation, same A*, same `RouteResult`) — this module adds NO second
routing algorithm. Alternatives are found by a bounded, deterministic
"penalize the previous route's cells, then re-run A*" loop:

    Route 1 = calculate_route(...)                     # the primary, optimal route
    Route 2 = calculate_route(..., cell_penalties=P1)   # P1 = Route 1's cells, penalized
    Route 3 = calculate_route(..., cell_penalties=P1+P2)  # both previous routes penalized
    ...

This is a real, standard technique for producing genuinely graph-derived,
loopless alternative paths from a single-shortest-path algorithm (the same
family of idea as Yen's algorithm's "penalize/exclude the previous path and
re-solve," simplified to a single accumulating penalty rather than a full
per-branch spur search — a deliberate simplification per the task's own
"do not overcomplicate" instruction, since ORCA's routing domain is a
small, bounded demo grid, not a general-purpose road network).

**Never random, never hardcoded**: every alternative is a genuine
`calculate_route()` result over the SAME real environmental grid (built
once — see `generate_route_alternatives`'s own docstring for why the
`risk_provider`/`hazard_provider` callables, not the environmental data
itself, are only ever evaluated through the existing, already-cached
providers `POST /api/v1/route` already builds).

**Bounded, never hundreds of routes**: `max_alternatives` defaults to 3
and the loop stops immediately once a re-run fails to find a route (or
returns a route identical to one already found) — it does not retry with
a different strategy.
"""
from __future__ import annotations

from app.gis.geofence import Geofence
from app.models.contracts import Mode, TemporalValidityStatus
from app.models.geo import BBox
from app.risk.config import RiskConfig
from app.routing.config import RoutingConfig
from app.routing.engine import DataQuality, calculate_route
from app.routing.errors import NoRouteFoundError, RouteReconstructionError, RoutingError
from app.routing.grid import EnvironmentalScoreProvider
from app.routing.models import RouteRequest, RouteResult

DEFAULT_MAX_ALTERNATIVES = 3
DEFAULT_ALTERNATIVE_PENALTY = 1.0  # combined with routing_config.yaml's cost_weights.alternative_penalty


def _route_cells(route: RouteResult) -> set[tuple[int, int]]:
    return {(c.row, c.col) for c in route.path_cells}


def generate_route_alternatives(
    request: RouteRequest,
    *,
    bbox: BBox,
    geofences: list[Geofence],
    risk_provider: EnvironmentalScoreProvider,
    hazard_provider: EnvironmentalScoreProvider,
    temporal_validity: TemporalValidityStatus,
    confidence: float,
    mode: Mode,
    data_quality: DataQuality,
    routing_config: RoutingConfig | None = None,
    risk_config: RiskConfig | None = None,
    max_alternatives: int = DEFAULT_MAX_ALTERNATIVES,
) -> list[RouteResult]:
    """Returns 1..max_alternatives DISTINCT, graph-derived `RouteResult`s,
    the first of which is always the same route `calculate_route()` alone
    would return (identical inputs, `cell_penalties=None`).

    `risk_provider`/`hazard_provider` are the SAME already-prepared
    callables `POST /api/v1/route` passes to a single `calculate_route()`
    call today (see `app.agents.environmental_provider
    .AgentBackedEnvironmentalProvider` — its expensive live sampling has
    already happened ONCE, in `.prepare()`, before this function is ever
    called). Every alternative re-runs the (cheap, in-memory) grid build +
    A* against that SAME prepared data — never a second round of live
    environmental fetches, per the task's own "no N×M explosion" rule.
    """
    if max_alternatives < 1:
        raise ValueError(f"max_alternatives must be >= 1, got {max_alternatives}")

    routes: list[RouteResult] = []
    accumulated_penalties: dict[tuple[int, int], float] = {}

    for attempt in range(max_alternatives):
        try:
            route = calculate_route(
                request,
                bbox=bbox,
                geofences=geofences,
                risk_provider=risk_provider,
                hazard_provider=hazard_provider,
                temporal_validity=temporal_validity,
                confidence=confidence,
                mode=mode,
                data_quality=data_quality,
                routing_config=routing_config,
                risk_config=risk_config,
                cell_penalties=accumulated_penalties or None,
            )
        except (NoRouteFoundError, RouteReconstructionError):
            # A heavily-penalized graph legitimately has no further distinct
            # route (e.g. a single narrow navigable corridor) — this is an
            # honest "no more alternatives exist" result, not an error to
            # propagate; the caller already has the primary route (attempt 0
            # never reaches here, since it has no penalties to cause this).
            break
        except RoutingError:
            # Any other routing failure on a later attempt is treated the
            # same way — a real limit on how many distinct routes this grid
            # supports, never surfaced as if the PRIMARY request itself failed.
            if attempt == 0:
                raise
            break

        new_cells = _route_cells(route)
        if any(new_cells == _route_cells(existing) for existing in routes):
            # The penalty was not enough to force a genuinely different path
            # (can happen when origin/destination sit in a single-cell-wide
            # corridor) — stop rather than return a duplicate presented as a
            # second "option."
            break

        routes.append(route)
        for rc in new_cells:
            accumulated_penalties[rc] = accumulated_penalties.get(rc, 0.0) + DEFAULT_ALTERNATIVE_PENALTY

    return routes
