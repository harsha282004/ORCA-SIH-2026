# Phase 5 — Advanced Marine Routing Report

**Status:** Complete. Deterministic alternative-route generation, route-level Safety Guard/Decision classification, deterministic route comparison, and Ask ORCA conversational routing are implemented, live-verified against the real environmental pipeline, and covered by 31 new backend tests. Frontend typecheck/lint/build are clean; a live Puppeteer pass exercised the full Route Planner (including alternatives, comparison, and the risk-beats-distance recommendation) and Ask ORCA routing in a real browser with zero console errors.

---

## 1. Executive Summary

Phase 5 upgrades ORCA's Route Planner from "one route + a risk cost" to marine-aware routing with real hazard exposure, a deterministic safety verdict per route, bounded alternative-route generation, and deterministic comparison — all reusing the existing hand-rolled A* engine, Risk Engine, Safety Guard, Decision Engine, and Phase 4's `hazards_near_route` unchanged. No new routing algorithm, no new risk/safety formula, no LangGraph topology change. The one genuinely new mechanism is a documented, additive 5th edge-cost term (`alternative_penalty_cost`, default 0.0) that lets the same A* search be re-run to find a distinct route without ever weakening a hard constraint.

## 2. Existing Routing Architecture (Audit Findings)

Read in full before any change: `app/routing/engine.py`, `astar.py`, `grid.py`, `costs.py`, `config.py`, `validation.py`, `errors.py`, `models.py`, `app/agents/environmental_provider.py`, `app/api/v1/route.py`.

- **No NetworkX anywhere in the codebase** (confirmed via `grep -rn networkx` — zero matches, and it is not even in `requirements.txt`). `architecture.md` §26 itself says "A* (Haversine heuristic) via `networkx` **or a custom implementation**" — a custom, hand-rolled `heapq`-based A* (`app/routing/astar.py`) was the choice actually made, and it is a real, deterministic, well-tested implementation (53 pre-existing tests). Phase 5 does **not** introduce NetworkX: doing so now would be a bigger architectural change than the task's "extend minimally" instruction supports, and the existing engine already does everything needed.
- **Graph construction**: `app.routing.grid.build_routing_grid` rasterizes the bbox into a dict-keyed `{(row,col): RoutingNode}` grid once per route calculation, annotating each cell with navigability (hard geofences), `risk_score`, `hazard_score`, and `geofence_soft_penalty` — no separate NetworkX/graph-library object.
- **Edge cost** (architecture.md §26, verbatim pre-Phase-5): `edge_cost = distance_cost + environmental_risk_cost + hazard_cost + geofence_cost`, each term scaling with the haversine distance actually traveled through the destination cell.
- **Risk/hazard integration**: `app.agents.environmental_provider.AgentBackedEnvironmentalProvider` does ONE bounded (default 4×4=16-point) live Weather+Oceanographic sampling pass per route request, then a nearest-neighbor lookup assigns every grid cell its risk/hazard score — never one live call per cell.
- **Geofence handling**: polygon-vs-polygon intersection (not just centroid), producing a hard `navigable=False` for any cell touching a hard geofence; a *soft* penalty scales with distance to the nearest hard geofence for cells that are merely nearby.
- **Route distance / confidence / provenance**: `RouteMetrics.total_distance_km` (summed haversine), `RouteResult.confidence` (the environmental provider's own worst-case confidence across all samples), and `app.provenance.models.RouteProvenance`/`DecisionProvenanceGraph.route` already existed — pre-scaffolded for exactly this phase, previously unused because `route()` was a stub.
- **Temporal behavior**: `RouteRequest.requested_time` already flows into cache keys and the confidence/temporal-validity gate; the known Phase 3 `requested_time`-ignored-by-single-value-agents bug (§19 below) was **not** touched.

**Conclusion: nothing was replaced.** Every extension below is additive to this existing engine.

## 3. Routing Engine Audit — What Changed, Precisely

| File | Change | Why |
|---|---|---|
| `app/routing/grid.py` | `RoutingNode` gained `alternative_penalty: float = 0.0` | A soft, per-cell diversity signal for alternative-route generation. Default 0.0 = byte-identical to Phase 3/4 for every existing caller. |
| `app/routing/config.py` | `RoutingCostWeights` gained `alternative_penalty: float = 0.0` | Configurable weight for the new term; default preserves every existing 4-arg construction across the test suite. |
| `app/routing/routing_config.yaml` | `cost_weights.alternative_penalty: 8.0` | The production weight — documented in the file itself. |
| `app/routing/costs.py` | `compute_edge_cost` gained a 5th additive term, `alternative_penalty_cost = weights.alternative_penalty * to_node.alternative_penalty * distance_km` | Exact same "scales with distance" pattern as the other four terms; `EdgeCostBreakdown` gained the matching field. |
| `app/routing/engine.py` | `calculate_route` gained an optional `cell_penalties: dict[(row,col), float] \| None = None` parameter, applied to navigable cells only, after the grid is built | The ONLY mechanism used to steer a re-run toward a different corridor — never touches `navigable`. `RouteMetrics` gained `alternative_penalty_cost` (summed from edges). |
| `app/routing/models.py` | `RouteRequest.max_alternatives: int = 1` (1-5); new `RankedRoute`/`RouteComparisonResult` models | `max_alternatives=1` (default) is the exact pre-Phase-5 request shape. |

Existing routing behavior for `max_alternatives=1` was proven byte-identical: `tests/routing/test_alternatives.py::test_first_alternative_is_identical_to_the_plain_calculate_route_result` asserts the cell sequence returned by `generate_route_alternatives(..., max_alternatives=1)` equals a direct `calculate_route()` call exactly.

## 4. Marine-Aware Routing — What Actually Feeds Into Routing

Confirmed by reading `app.agents.environmental_provider` before claiming anything:

- **Distance** — real haversine, per edge.
- **Wave/wind risk** — real, live Open-Meteo-derived Risk Engine score (`environmental_risk_cost`), sampled at up to 16 points per route and nearest-neighbor-assigned to every grid cell.
- **Lightning/thunderstorm proxy** — the existing WMO-weathercode-based proxy (`hazard_cost`), same source as Phase 4's `THUNDERSTORM_PROXY` hazard, never claimed as authoritative.
- **Geofences** — hard (navigable=False) and soft (distance-based penalty), from the same non-authoritative demo fixture set used everywhere else in the project.
- **Cyclone hazards (Phase 4)** — via `hazards_near_route`, checked against the ALREADY-computed path, never priced into the A* cost itself (see §6).

**NOT used by routing, and never claimed to be**: SST (Open-Meteo or INCOIS), chlorophyll, or GEBCO bathymetry. The routing engine has no code path that reads any of these three — confirmed by grep across `app/routing/` and `app/agents/environmental_provider.py`. Phase 5 does not add one (task §18's explicit "do not claim route avoids shallow water unless the engine actually performs that calculation" — it does not, and this report does not claim otherwise).

## 5. Safety Precedence

Unchanged hierarchy, now applied per-route via `app.routing.safety.evaluate_route_safety`:

```
HARD SAFETY CONSTRAINTS (hard geofence)   -> structurally impossible in any returned RouteResult
        |
HAZARD (a real DANGER/CRITICAL cyclone near the path) -> BLOCK_HAZARD -> NO_SAFE_RECOMMENDATION
        |
RISK (max per-cell risk score along the route)         -> LOW/MODERATE/HIGH -> RECOMMEND/CAUTION/(ALTERNATIVES|BLOCK)
        |
ROUTE COST (A*'s own optimization, already computed)
        |
DISTANCE / PREFERENCE                                   -> tie-breaker ONLY (see §9 compare_routes' sort key)
```

`has_boundary_violation` and `has_critical_missing_data` are **structurally always False** by the time a `RouteResult` exists — `calculate_route` already raises `RouteReconstructionError`/`RouteDataQualityError` before ever returning one if either would be true. This is documented, not assumed, in `app/routing/safety.py`'s own module docstring, and verified live: `test_route_endpoint_rejects_destination_inside_land_fixture` (pre-existing, unaffected) still returns `422 BLOCKED_LAND_OR_GEOFENCE` before any `RankedRoute` is ever built.

A shorter route never outranks a safer one: `app.routing.comparison.compare_routes`'s sort key is `(safety_blocked, decision_rank, risk_rank, risk_score, distance_km)` — distance is the **last** field, never the primary key. Live-verified (§8): a 69.2 km route with a lower max risk score was recommended over two ~60.2 km alternatives.

## 6. Hazard-Aware Routing

`hazards_near_route` (Phase 4, `app/hazard/route_hazards.py`) is reused **verbatim, unmodified** — no duplicate hazard-intersection engine was built. It is called once per candidate route (primary + each alternative), against that route's own `path_coordinates`, using the same haversine-based relevance check and the same Redis-cached GDACS cyclone feed every other hazard consumer uses (a cache hit is shared across all routes in one request — no repeated GDACS calls). Wave/wind hazards are **not** duplicated here: they are already priced into the route's own A* cost (`environmental_risk_cost`/`hazard_cost`), and re-exposing them as a second "hazard near route" signal would be a competing, redundant representation of the same real data (documented in `route_hazards.py`'s own docstring, unchanged from Phase 4).

When no hazard exists, the response says exactly what the task requires: `"No relevant hazards detected from available data."` (frontend `RoutePlanner.tsx`) — never "route is guaranteed safe." Live-verified via the browser E2E pass (§20).

## 7. Route Risk

No second risk score. `evaluate_route_safety` classifies `route.metrics.max_risk_score` (the worst single grid cell crossed) via the EXISTING `app.risk.engine.classify_risk_level` and the EXISTING `RiskThresholds` (0.33/0.66) — the same function/thresholds every other ORCA surface uses. `average_risk_score` remains separately available on `RouteMetrics` for "what are typical conditions along this route," never conflated with the safety-relevant "worst case" number. Every route (primary and alternatives) exposes: `risk_level`, `metrics.average_risk_score`, `metrics.max_risk_score`, `hazards_near_route`, `decision` (RECOMMEND/RECOMMEND_WITH_CAUTION/PROVIDE_ALTERNATIVES/NO_SAFE_RECOMMENDATION), and `confidence` — the exact fields task §9 asks for.

## 8. Alternative Route Generation

`app/routing/alternatives.py::generate_route_alternatives` — a bounded (`max_alternatives`, 1-5, default 3 for conversational queries, capped at 5 by the API's own Pydantic validation), deterministic "penalize the previous route's cells, then re-run the SAME A*" loop, documented as a simplified relative of Yen's algorithm (chosen over introducing NetworkX's `shortest_simple_paths`, per §2's reasoning). Every alternative is a genuine `calculate_route()` result over the SAME already-sampled environmental data — **zero additional live HTTP calls per alternative**. The loop stops (never errors) the moment a re-run fails to find a route, or returns a path identical to one already found — an honest "no further distinct alternative exists" result, never a fabricated duplicate presented as a new option.

**Live-verified** (`POST /api/v1/route`, `max_alternatives=3`, real Mangaluru–Udupi corridor):

```
Route A: 60.22 km, LOW risk
Route B: 60.22 km, LOW risk
Route C: 69.22 km, LOW risk  <-- genuinely longer, genuinely different path
recommended_label: "C"        <-- lower max risk score (0.260) than A/B, wins despite +9km
```

This is the task's own §14 worked example, reproduced with real numbers, not a hypothetical.

## 9. Route Comparison

`app.routing.comparison.compare_routes` — a pure function over already-computed `RankedRoute`s (no risk/safety computed here, only ranked). Sort key: `(safety_blocked, decision_outcome_rank, risk_level_rank, risk_score, distance_km)`. If every candidate is blocked, `recommended_label` is `None` and the reason explicitly says none passed deterministic safety checks — never "the least-bad option is safe." The reason string is a template built from the same real numbers shown in `routes`, never an LLM generation; Groq may re-phrase it conversationally (Ask ORCA) but never overrides it.

## 10. Temporal Routing

`RouteRequest.requested_time` was already wired into `AgentBackedEnvironmentalProvider`'s cache keys and confidence/temporal-validity computation before Phase 5 — unchanged. Phase 5 does not add a dedicated "route at 06:00 vs 12:00 vs 18:00" comparison UI/endpoint: doing so honestly would require the SAME `parse_hourly_timeseries` workaround Phase 3/4 already established (since `AgentBackedEnvironmentalProvider.prepare()` ultimately calls the single-value `WeatherIntelligenceAgent.get_weather(requested_time=...)`, which still has the documented "ignores `requested_time` when selecting the forecast hour" bug), and building a genuinely time-varying MULTI-SAMPLE routing grid (16 sample points × N hours, each via the real hourly-series path) was judged out of this phase's "bounded, no N×M explosion" budget — a real limitation, recorded in §24, not silently worked around with a second bug.

## 11. Route Confidence

Unchanged: `RouteResult.confidence` is the environmental provider's own worst-case sample confidence, distinct from `risk_level` (route quality) — the two are shown side by side in the frontend's "Selected Route" panel (`Confidence: 100%` / `Max risk score: 0.258` in the live E2E run, §20). A future genuinely sparse-data scenario would show a lower `confidence` alongside a LOW `risk_level`, exactly matching task §21's "low risk but limited confidence" example; this phase did not need to change the confidence *computation* itself to achieve that — it was already independent of risk.

## 12. Data Freshness

Unchanged `temporal_validity`/`data_quality` fields continue to gate route computation before any `RouteResult` exists (`validate_environmental_data_quality`, §5). No route response can silently present stale environmental data as current — the SAME Temporal Validity Gate that has governed every other ORCA surface since Phase 1 governs routing too, untouched.

## 13. Geofence Handling

Unchanged. The Phase 3/4 demo geofence set remains explicitly non-authoritative (`is_authoritative=False`, unchanged), and this report makes the same disclosure every prior phase's report makes: it is illustrative/demo geometry, never an official maritime restricted zone. One incidental finding from live E2E testing (§17): the gazetteer's "Mangaluru" reference point (12.87, 74.85) falls inside this demo land-fixture polygon, so a conversational route request literally naming "Mangaluru" as the origin is blocked at the origin-validation stage before routing ever runs — a pre-existing Phase 1-era gazetteer/geofence-precision interaction, not something Phase 5 introduced, but newly *visible* because Phase 5 is the first time a named place feeds directly into route origin/destination resolution.

## 14. Bathymetry Limitations

Unchanged: GEBCO remains ~225 real sampled points, informational/reference only. Routing does not read bathymetry at all (confirmed in §4) — no claim of "avoids shallow water" is made anywhere in this phase's code, UI copy, or this report.

## 15. Route Planner UI

`frontend/src/components/app/RoutePlanner.tsx` and `frontend/src/routes/RoutePlannerPage.tsx` (both enhanced, not replaced — same file, same route, same map engine):

- A "Find alternative routes for comparison" checkbox (`max_alternatives: 3` vs `1`).
- A **Route Options** list — one row per generated route, showing distance, a risk badge (LOW/MODERATE/HIGH, color-coded), a decision label (RECOMMENDED/CAUTION/BLOCKED), and an "ORCA PICK" marker on `comparison.recommended_label`. Clicking a row selects it.
- A **Comparison** panel showing the real, backend-generated `reason` string.
- A **Selected Route** panel: risk badge, safety outcome, distance, confidence, average/max risk score, real hazard count (or the exact "No relevant hazards detected from available data." string), hazard data source tier, and the existing disclaimer.

No second map engine, no new routing page — `/route-planner` is the same route, enhanced.

## 16. Marine Map Integration

`buildAlternativeRoutesLayer` (new) renders non-selected route options as a distinct muted-slate (or red, if `NO_SAFE_RECOMMENDATION`) line, visually separate from the selected route's existing segment-risk-colored `buildRouteRiskLayer` output and from the real hazard markers (`buildHazardsLayer`, reused from Phase 4, fed the SELECTED route's own `hazards_near_route`). `MapLegend.tsx` gained explicit "Selected route" / "Alternative route (not selected)" / "Blocked route option (unsafe)" entries — the task's own §25 visual-distinctness requirement. `/marine-map`, `/fishing`, and `/safety` were re-verified live (§20) to confirm zero regression: their own route/hazard/fishing layers still render and toggle correctly.

## 17. Ask ORCA Integration

**The genuine capability gap this phase closed**: the Query Understanding Agent previously resolved only ONE place name (`location_name`); a route needs two. `RawIntentResult`/`IntentResult` gained one new optional field each (`destination_name`/`destination`, defaulting to `None`) — resolved through the exact same deterministic `resolve_location` gazetteer lookup `location_name` already uses, never a second resolution mechanism, never LLM-computed coordinates. An unrecognized destination returns `ClarificationNeeded` exactly like an unrecognized origin. No new intent class was created — `route_planning` already existed.

The LangGraph `route` node (previously a permanent stub returning "call `POST /api/v1/route` directly") now actually runs the full deterministic pipeline — `generate_route_alternatives` → `hazards_near_route` → `evaluate_route_safety` → `compare_routes` — when a destination was resolved, reusing the SAME `AgentBackedEnvironmentalProvider` the direct endpoint uses (injectable via a new, optional `OrchestrationNodes.__init__` parameter, defaulting to the real provider). **Zero LangGraph topology change**: no new node, no new edge, the existing `after_decision` gate (`intent.requires_route AND origin-point safety PASS`) is untouched. The route's own `Decision`/`SafetyGuardResult` overwrite the origin point's (already-computed, now superseded) ones for this one query — `DecisionProvenanceGraph.decision`/`.route` were already designed, in an earlier phase, to carry exactly one query-level Decision alongside a `RouteProvenance` sibling; this is the first phase to actually populate both together.

**A live-testing-caught bug, fixed within this phase**: initially, `_build_provenance` still built `RiskProvenance` from the ORIGIN point's own `risk_suitability` even when a route existed, so the Evidence Agent's explanation cited the wrong risk score (origin's 0.13 instead of the route's 0.254) and an irrelevant fishing-suitability figure. Fixed by overriding `risk_provenance` with the route's own `(risk_score, risk_level)` — already available on the route's `Decision` — and suppressing `suitability_provenance` entirely for a route query (fishing suitability has no bearing on "is this route safe"). Re-verified live: the explanation now says *"risk is low (score 0.25)"*, matching the route's actual `decision.risk_score` (0.2544) exactly, with no mention of unrelated fishing suitability.

Supported conversational patterns, live-verified: *"Plan a safe route from Udupi to Malpe"* → real 4.2 km route, RECOMMEND, Groq explanation grounded in the real number.

**Follow-up questions** ("What about the alternative?", "Which route is safer?"): this phase relies entirely on the EXISTING generic multi-turn mechanism (`session.last_intent`/`last_decision`/`last_provenance`, `resolve_reference`) — no route-specific follow-up logic was added, per the explicit "do not redesign session architecture" instruction. This is a genuine, disclosed scope boundary (§24), not a silent gap.

## 18. Evidence & Provenance

`RouteProvenance` (pre-existing model, previously unused since `route()` never populated `state.route`) is now genuinely populated: `distance_km`, `total_cost`, `feasibility_status` from the real route. `RiskProvenance` is route-aware (§17). No new provenance model was created — task §15/§30's "extend, don't duplicate" instruction followed exactly.

## 19. API Changes

`POST /api/v1/route` — the ONLY routing endpoint; no new endpoint was created (task §30's explicit "avoid unnecessary endpoint proliferation").

- **Request**: `RouteRequest.max_alternatives: int = 1` (range 1-5, Pydantic-validated — a value outside range returns `422` before any routing logic runs, live-verified).
- **Response**: additive only, never shape-shifting:
  - `data` (unchanged shape) gains `label` ("A"), `risk_level`, `safety`, `decision` — always present, even for a plain `max_alternatives=1` request.
  - `alternatives: []` and `comparison: null` when `max_alternatives<=1` or no distinct alternative was found — an existing caller reading only `data`/`confidence`/`errors` is provably unaffected (`test_route_endpoint_default_response_includes_route_level_safety_fields`).
  - `alternatives: [...]`, `comparison: {recommended_label, reason, generated_at}` when more than one route was generated.

`POST /api/v1/query` — `data` gains `route`, `route_alternatives`, `route_comparison` (all `None`/`[]` unless a route_planning query with a resolvable destination actually computed one); `marine_safety`'s hazard list now correctly switches to the route's own hazards (`route_hazards`) instead of the origin point's, whenever a route was computed (a Phase 4→5 consistency fix, since Phase 4 only ever had origin-point hazards to show).

## 20. Testing

**Backend: 611 passed, 2 pre-existing failures** (up from Phase 4's 580/2 baseline — **31 new tests, zero new failures, the exact same 2 pre-existing failures by name**):

- `tests/routing/test_alternatives.py` (6) — first-alternative-identical-to-plain-call, genuine distinctness, wall-avoidance, bounded+deterministic, graceful "fewer than requested" handling, input validation.
- `tests/routing/test_route_safety.py` (7) — LOW/MODERATE/HIGH → RECOMMEND/CAUTION/(NO_SAFE_RECOMMENDATION or PROVIDE_ALTERNATIVES), a real CRITICAL hazard blocking despite low risk, an ADVISORY hazard NOT blocking, determinism.
- `tests/routing/test_comparison.py` (6) — lower-risk-beats-shorter-distance (task's own worked example, reproduced exactly), a blocked route never winning over a passing one, all-blocked → no recommendation, single-route/empty-list edge cases, distance-only-breaks-ties-at-equal-risk.
- `tests/routing/test_api_route.py` (+3) — default response carries route-level safety fields with `alternatives=[]`/`comparison=null`, bounded real alternatives with a real recommendation, out-of-range `max_alternatives` rejected with 422.
- `tests/agents/query_understanding/test_agent.py` (+4) — two-place resolution, single-place leaves destination `None`, unrecognized destination → clarification (never a guess), non-routing intents never populate destination.
- `tests/orchestration/test_route_node.py` (5, new file) — a real conversational route computed end-to-end through the graph, honest fallback when no destination is named, a calm route recommends with no critical hazard, the route's decision (not the origin's) is what the query returns, deterministic repeatability.

All new tests run fully offline (`FakeEnvironmentalProvider`, `FakeHazardCache`/`FakeCache`, the real network-free GIS agent) — verified by timing (the full `tests/routing` + `tests/orchestration` suites run in under 3 seconds combined, ruling out any accidental live network/GDACS call from the new alternative-generation or hazard-checking code paths).

**Frontend**: `npx tsc --noEmit` — 0 errors. `npm run lint` (ESLint) — 0 errors/warnings. `npm run build` — succeeds (`RoutePlannerPage` bundles at 13.83 kB, up from 9.88 kB, still individually code-split).

**E2E (live Puppeteer, headless Edge, against the running Docker stack)**:
1. `/route-planner`: submitted a real origin/destination with "find alternatives" checked → real Route A/B/C rendered (60.2/60.2/69.2 km), correct risk badges, "ORCA PICK" on the actually-lower-risk (longer) route, comparison reasoning text present, hazard status shown, map canvas rendered — **zero console errors**.
2. `/marine-map`, `/fishing`, `/safety`: re-verified — hazard/fishing/safety layers and pages unaffected — **zero console errors** (Phase 4's regression suite re-run in full).
3. `/ask-orca`: "Plan a safe route from Udupi to Malpe" → real 4.2 km route, RECOMMEND, explanation grounded in the real risk score (0.25) — **zero console errors**, and network monitoring confirmed the browser made **no direct calls to Open-Meteo/GDACS/any external data provider** (only the app's own origin, `localhost:8000`, and Google Fonts).

## 21. Docker

`docker compose build backend && up -d backend`, `docker compose build frontend && up -d frontend` — both succeeded. `docker compose ps`: all four containers (`orca-backend`, `orca-frontend`, `orca-postgres`, `orca-redis`) healthy/running. `GET /health` → `{"status":"ok"}`. `GET /api/v1/health/ready` → `{"status":"ready", "dependencies": {"database":"healthy","postgis":"healthy","redis":"healthy"}}`.

## 22. Performance

- Alternative-route generation adds **zero additional live HTTP calls** — every alternative re-runs the (in-memory, millisecond-scale) grid build + A* against the SAME already-sampled environmental data. Live-measured: a 3-alternative `POST /api/v1/route` request completed in **3.68 s total** (dominated entirely by the one environmental-sampling pass, identical to a single-route request's own latency).
- A conversational route query (Ask ORCA) pays the origin-point's own small weather/marine fetch (§17) *plus* the route's full environmental sampling pass *plus* one Groq call — measured at **7-34 s** across two live runs (the faster run benefited from Redis caching the environmental samples from the immediately-preceding run at the same location/time bucket). This is real, honestly higher than the direct `/route` endpoint's own ~10-15s, and is disclosed here rather than understated.
- The GDACS cyclone cache is shared across every route/alternative in one request (confirmed live: `hazard_source_tier: "cached"` on a route request issued shortly after a `/safety/*` call to the same region) — never re-fetched per candidate.

## 23. Files Changed

**New**: `backend/app/routing/alternatives.py`, `backend/app/routing/safety.py`, `backend/app/routing/comparison.py`; `backend/tests/routing/test_alternatives.py`, `test_route_safety.py`, `test_comparison.py`; `backend/tests/orchestration/test_route_node.py`; this report.

**Modified**: `backend/app/routing/grid.py`, `config.py`, `costs.py`, `engine.py`, `models.py`, `routing_config.yaml`; `backend/app/api/v1/route.py`, `query.py`; `backend/app/agents/query_understanding/models.py`, `agent.py`; `backend/app/orchestration/state.py`, `nodes.py`; `backend/tests/routing/test_api_route.py`; `backend/tests/agents/query_understanding/test_agent.py`; `backend/tests/orchestration/conftest.py`. `frontend/src/lib/api.ts`; `frontend/src/components/app/RoutePlanner.tsx`; `frontend/src/routes/RoutePlannerPage.tsx`; `frontend/src/components/map/mapLayers.ts`, `EvidencePanel.tsx`, `MapLegend.tsx`.

## 24. Known Limitations

1. **Temporal routing** (task §19) is not exposed as a dedicated "route at 06:00 vs 12:00 vs 18:00" feature — `requested_time` is honored for the single environmental snapshot a route uses, but a genuinely time-varying multi-hour routing comparison would require re-sampling the whole grid per hour via the proven-but-heavier `parse_hourly_timeseries` path, judged out of this phase's performance budget (§10).
2. **Conversational route follow-ups** ("what about the alternative?") rely entirely on the existing generic session/reference mechanism, not a route-specific one — untested for this specific phrasing pattern (§17).
3. **The "Mangaluru" gazetteer point falls inside the demo land-fixture polygon** (§13) — a pre-existing Phase 1 imprecision, newly visible because Phase 5 is the first time a named place feeds directly into route origin/destination.
4. `app.fishing.engine`'s own cyclone-outage handling (a Phase 4-documented gap) is unchanged; Phase 5's route-level hazard check inherits the same "empty list on GDACS failure" behavior rather than `/api/v1/safety`'s stricter `UNKNOWN`-forcing behavior — recorded, not newly introduced.
5. Alternative-route diversity depends on the grid genuinely having more than one viable corridor; a single-corridor origin/destination pair correctly returns just 1 route (verified: `test_requesting_more_alternatives_than_the_grid_supports_returns_fewer_not_an_error`), never a fabricated "alternative."

## 25. Technical Debt

- The Phase 3 `requested_time`-ignored-by-single-value-agents bug remains unfixed (by explicit instruction, again) — the routing engine's own `requested_time` handling only reaches as far as `AgentBackedEnvironmentalProvider`'s cache-key/confidence computation, not the underlying agents' hour-selection logic.
- The Redis GIS-dataset-status cache-staleness issue (Phase 1, unrelated to route safety data) remains open, unaddressed by this phase (it does not feed into any route safety decision).
- Phase 4's documented lightning-unavailable-doesn't-force-UNKNOWN gap and fishing-engine cyclone-outage gap are both inherited unchanged into route-level hazard checks (item 4, §24).
- `app.routing.alternatives`' single-accumulating-penalty technique is a deliberate simplification of Yen's algorithm — it will not find every theoretically-possible k-shortest-loopless-path in unusual grid topologies (e.g., three-way symmetric corridors), though it is fully deterministic and bounded within the ones it does find.

## 26. Phase 6 Readiness

Yes, conditionally. The hazard/safety/decision/comparison machinery this phase built is cleanly layered on top of the existing engines with no reverse dependencies (`app.routing.safety`/`comparison`/`alternatives` depend on `app.hazard`/`app.decision`/`app.policy`/`app.risk`, never the other way around), so a future phase adding scenario/what-if simulation, alert delivery, or multilingual route explanations can consume `RankedRoute`/`RouteComparisonResult` directly. The disclosed gaps in §24/§25 (temporal routing, route-specific follow-ups, the Mangaluru gazetteer/geofence interaction) are each small, well-scoped follow-ups, not architectural blockers.
