# Phase 3 — Deterministic Risk-Aware Routing

This document describes what is actually implemented for Phase 3. See
[`docs/architecture.md`](architecture.md) §26 (Route Optimization) for the frozen
architecture this implements against, and [`docs/deterministic_core.md`](deterministic_core.md)
for the Phase 2 GIS/Risk/Confidence/Geofence components this phase reuses without
duplication.

**Stated plainly, per architecture.md's own discipline (§47, §26): a route returned by
this engine is optimal with respect to ORCA's own configured deterministic cost model. It
is NOT an official maritime navigation recommendation, and it is NOT guaranteed to be the
globally safest possible route** — only the lowest-cost one under the weights in
`routing_config.yaml`.

```
ROUTE REQUEST
     |
     v
DATA-QUALITY GATE        (reuses Phase 1 Temporal Validity Gate + Phase 2 confidence)
     |
     v
RESOURCE-SAFETY CHECK     (grid cell count vs. configured max_cells)
     |
     v
BUILD ROUTING GRID        (reuses Phase 2's app.gis.grid.generate_grid)
     |
     v
LAND / GEOFENCE MASK      (reuses Phase 2's app.gis.geofence — land is just a HARD category)
     |
     v
ORIGIN VALIDATION  ---->  fails here => OriginValidationError, A* never runs
     |
     v
DESTINATION VALIDATION -> fails here => DestinationValidationError, A* never runs
     |
     v
A* SEARCH                 (Haversine heuristic, reused from app.gis.distance)
     |
     v
PATH RECONSTRUCTION
     |
     v
ROUTE VALIDATION           (internal consistency — never a user-facing error)
     |
     v
ROUTE METRICS
     |
     v
STRUCTURED RouteResult
```

## 1. Routing architecture

`backend/app/routing/`: `models.py` (contracts), `config.py` + `routing_config.yaml`
(configuration), `errors.py` (typed failures), `grid.py` (the `RoutingNode` adapter over
Phase 2's `GridCell`), `costs.py` (edge cost), `astar.py` (the search itself),
`validation.py` (origin/destination/data-quality/post-route checks), `fixtures.py`
(demo-only geofence + risk/hazard placeholders), `engine.py` (orchestration).

Nothing here calls an LLM, LangGraph, or any agent. The entire module is importable and
fully testable with zero network access and no API key.

## 2. Grid representation

- **Resolution**: 3 km — Phase 2's own documented engineering default
  (`docs/deterministic_core.md` §6), reused here unchanged, not silently altered.
- **Cell**: Phase 2's `app.gis.grid.GridCell` (row/col, polygon geometry, centroid),
  wrapped by Phase 3's `RoutingNode` (`navigable`, `block_reason`, `risk_score`,
  `hazard_score`, `geofence_soft_penalty`) — no duplication of the grid-geometry
  algorithm itself. `app.gis.grid.grid_dimensions()` was extracted (pure refactor, zero
  behavior change, Phase 2 tests re-verified green afterward) so `locate_cell()` can find
  which cell a coordinate falls into using the exact same row/col layout `generate_grid`
  produces.
- **Neighbor model**: 8-connected (orthogonal + diagonal). See §5 for corner-cutting.
- **On the real demo bbox** (12.70–13.45°N, 73.50–75.05°E) at 3 km resolution: **28 rows
  × 57 cols = 1,596 cells** (measured, not estimated — see §12).

## 3. Land masking

**Land is not a separate code path.** `GeofenceCategory.LAND` is one of Phase 2's four
HARD geofence categories (`land`, `protected_area`, `international_boundary`,
`restricted_zone`); a land polygon blocks a cell through the exact same mechanism as a
protected area. Cell-level masking added one thing Phase 2 never needed:
`app.gis.geofence.evaluate_polygon_against_geofences()` (new function, additive — checks
whether a HARD geofence intersects a cell's **full polygon area**, not just its
centroid). This was a real bug caught during Phase 3 development (see §17) — a centroid-
only check let a hard obstacle thinner than one grid cell fall silently between two
centroids and never block anything.

**No real coastline data exists.** Phase 1 never acquired Natural Earth data (see
`docs/demo_region.md`). Every geofence in this phase's tests and in the default API
demo (`app.routing.fixtures.DEMO_LAND_FIXTURE`) is `source="fixture"`,
`is_authoritative=False`, and explicitly named to say so. When real coastline/WDPA/EEZ
data is acquired, it satisfies the exact same `Geofence` interface — no change to the
grid, masking, or A* code is required.

## 4. Geofencing — hard vs. soft (reused from Phase 2, not reimplemented)

**Hard** (blocks the cell outright): `land`, `protected_area`, `international_boundary`,
`restricted_zone` (if active at the query time). **Soft** (never blocks, only adds cost):
proximity to a hard geofence, contributing to the edge cost's `geofence_soft_penalty`
term via Phase 2's own `restricted_zone_distance_risk()` — reused verbatim, not
reimplemented as a second formula.

## 5. Cost function

Architecture §26's literal formula: `edge_cost = distance_cost + environmental_risk_cost
+ hazard_cost + geofence_cost`. Phase 3 keeps that exact four-term additive structure and
adds configurable coefficients (per architecture §4's "configuration over hardcoding"
principle — weight 1.0 on all four reduces to the literal formula):

```yaml
cost_weights:
  distance: 1.0
  environmental_risk: 5.0
  hazard: 5.0
  geofence_soft: 3.0
```

For an edge into cell `to_node`, with `d` = Haversine distance in km between cell centroids:

```
distance_cost            = weights.distance × d
environmental_risk_cost  = weights.environmental_risk × to_node.risk_score × d
hazard_cost               = weights.hazard × to_node.hazard_score × d
geofence_cost              = weights.geofence_soft × to_node.geofence_soft_penalty × d
```

Risk/hazard/geofence costs scale with distance traveled through a cell — the same
pattern architecture §26's cited precedent (VISIR-2) uses for weather-routing edge costs,
so a long stretch through moderately risky water costs more than a brief one. **These
coefficients are ORCA engineering parameters, not regulatory maritime standards** — same
status as the Risk Engine's own weights.

Risk and hazard values themselves are never recomputed independently — `RoutingNode.risk_score`
is populated by calling Phase 2's own risk-component functions (or, in tests, an injected
fixture provider); routing never invents a second risk formula.

## 6. A*

- **Search**: standard A*, `g(n)` = accumulated edge cost, `f(n) = g(n) + h(n)`.
- **Heuristic**: `h(n) = weights.distance × haversine_km(n, destination)` — reused
  directly from `app.gis.distance.haversine_km`, no second Haversine implementation.
  Scaling the heuristic by the same coefficient the edge cost uses keeps it an
  admissible lower bound: every other cost term is `>= 0`, so true edge cost is always
  `>= weights.distance × distance`, regardless of how risky the path turns out to be.
  Risk/hazard were deliberately **not** folded into the heuristic — doing so cannot be
  proven admissible without knowing the grid's least-risky-per-km value in advance.
- **Neighbor model**: 8-connected, with **corner-cutting explicitly prevented** — a
  diagonal move from `(r,c)` to `(r+dr,c+dc)` is only legal if both orthogonal cells
  `(r+dr,c)` and `(r,c+dc)` are also navigable. Verified by
  `tests/routing/test_astar.py::test_corner_cutting_is_prevented` (a 4×4 grid where the
  only diagonal shortcut is corner-blocked, forcing and verifying a longer detour) and
  `test_corner_cutting_allowed_when_both_orthogonals_open` (the direct diagonal is taken
  when it isn't cutting a corner).
- **Deterministic tie-breaking**: every heap entry is `(f_score, insertion_counter, cell)`
  — ties in `f_score` always resolve in insertion (FIFO) order, never via Python's
  incidental dict/set iteration order and never randomly.

## 7. Validation

- **Origin and destination are always validated before A* runs** (architecture §26's
  explicit requirement) — coordinate range, inside the configured routing domain (the
  server's bbox — not user-controlled, closing the resource-safety concern directly),
  point-level hard-geofence check, and cell-level navigability of the grid cell the point
  falls into (so a coarse grid can never disagree with the precise point check at a
  coastline edge). Any failure raises a typed `OriginValidationError` /
  `DestinationValidationError` before the grid's A* search is invoked.
- **Post-route validation** (`app.routing.validation.validate_route_path`) is an internal
  bug-detection pass, not a user-input check: path starts at origin, ends at destination,
  every cell is navigable, every consecutive pair is a legal neighbor, no duplicate
  cells, distance is positive when origin != destination, cost is finite. A failure here
  raises `RouteReconstructionError` — it has never actually fired in testing (a real A*
  bug would be required to trigger it), and it is documented as exactly that.

## 8. No route found

`app.routing.errors.NoRouteFoundError` — raised when A*'s open set is exhausted without
reaching the destination. Never a partial path, never the closest reachable cell, never a
relaxed-constraint fallback. Carries `expanded_nodes` for diagnostics. Verified by fully
partitioning the grid with a full-width hard geofence
(`test_fixture_d_full_width_hard_geofence_blocks_route`).

## 9. Route metrics

`RouteMetrics`: `total_distance_km`, `distance_cost`, `environmental_risk_cost`,
`hazard_cost`, `geofence_cost`, `total_cost`, `cell_count`, `average_risk_score`,
`max_risk_score`. **These are ORCA engineering metrics, not an official maritime
route-safety certification.**

## 10. Temporal validity and confidence

Reused verbatim from Phase 1 (`TemporalValidityStatus`) and Phase 2
(`RiskConfig.safety.min_confidence_threshold`) — no second formula. Before any grid work
happens, `validate_environmental_data_quality` refuses to route (raising
`RouteDataQualityError`) if the caller-supplied `temporal_validity` is `STALE`,
`EXPIRED`, `MISSING_TIMESTAMP`, or `INVALID_TIMESTAMP`, or if `confidence` is below the
Risk Engine's own configured minimum (0.5, documented in Phase 2 as an engineering
default, not a frozen architectural number). Low-confidence data never silently produces
a route that looks just as confident as one backed by good data.

## 11. Demo / live behavior

`RouteResult.mode` (session type, from `ORCA_MODE`) and `RouteResult.data_quality`
(`"fixture"` today, always) are kept as the same two independent concerns architecture
§16a establishes for observations. The `POST /api/v1/route` endpoint currently has no
live per-cell environmental data to consume — there is no live per-cell Marine Data
Fabric grid yet (that is Phase 4's Weather/Oceanographic Agent territory) — so it always
runs against `app.routing.fixtures`, clearly labeled, `data_quality="fixture"` in every
response. The engine itself takes `risk_provider`/`hazard_provider` as injected callables
and `geofences`/`data_quality`/`mode` as explicit parameters specifically so that when
real per-cell data exists, it is a **new implementation of the same interface**, not a
rewrite of `astar.py`, `costs.py`, or `engine.py`.

## 12. Performance (measured, on this machine)

| Metric | Value |
|---|---|
| Demo bbox grid dimensions | 28 rows × 57 cols = 1,596 cells |
| Navigable cells (with demo fixture geofence) | 1,316 |
| Blocked cells | 280 |
| Grid build time | ~85 ms |
| A* search time (12.80,74.20 → 13.30,74.10) | ~3 ms, 182 expanded nodes, 20-cell path |
| Full `calculate_route` (grid + A* + validation) | ~97 ms |

No premature optimization was applied — this is a straightforward `heapq`-based A* over
a dict-indexed grid, well within budget for the demo bbox's scale.

## 13. Limitations

- No real coastline/protected-area/EEZ data — all geofences are fixtures.
- No live per-cell environmental risk/hazard grid — the API endpoint uses a flat
  placeholder; the risk/hazard-aware *behavior* itself is fully implemented and tested
  against explicit fixtures (`tests/routing/test_risk_hazard_routing.py`), just not yet
  wired to real per-cell Open-Meteo data (Phase 4 concern).
- `distance_to_polygon_km` (reused from Phase 2) is an engineering approximation, not
  navigation-grade — see `docs/deterministic_core.md` §2.
- Route persistence (`routes`/`route_segments` tables, architecture §33) is deliberately
  **not implemented** — those tables have a `query_id` foreign key to a `queries` table
  that does not exist until a real query pipeline exists (Phase 4+). Building that schema
  now would mean inventing a foreign-key relationship to a nonexistent entity. Routes are
  returned directly in the API response and are not persisted.
- Single-route only — no multi-route ranking/alternates (architecture §41 lists this as
  SHOULD/STRETCH, not MUST).
