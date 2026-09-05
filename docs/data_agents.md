# Phase 4 — Data Agents

This document describes what is actually implemented for Phase 4. See
[`docs/architecture.md`](architecture.md) §10 (Agent Architecture) for the frozen
architecture this implements against, and [`docs/deterministic_core.md`](deterministic_core.md) /
[`docs/routing.md`](routing.md) for the Phase 2/3 components this phase wires together
without reimplementing.

## 1. Purpose

Phase 4 wraps Phase 1's data foundation (Open-Meteo adapters, the Marine Data Fabric,
Temporal Validity Gate) into three architecture-named service boundaries — Weather
Intelligence, Oceanographic Intelligence, and GIS & Geofencing — and wires their output
into Phase 3's routing engine, replacing its flat fixture placeholder with real
(bounded) environmental data. Per architecture §10's own table, none of these three
roles is an LLM call ("Real LLM agent? No" for all three); they are deterministic
service components, not autonomous agents. **Zero LLM calls, zero LangGraph, zero
natural-language generation anywhere in this phase.**

## 2. Architecture flow

```
Open-Meteo Weather ──────┐
                         │
Open-Meteo Marine ───────┼──> Marine Data Fabric (Phase 1, reused verbatim)
                         │
Static GIS (fixture) ────┘

                          Data Agents (Phase 4)
              ┌───────────────────┼───────────────────┐
              ↓                   ↓                    ↓
   Weather Intelligence   Oceanographic Intelligence   GIS & Geofencing
   Agent                  Agent                        Agent
   (LIVE→CACHED→STATIC)   (LIVE→CACHED→STATIC)         (fixture geofences,
                                                          static-dataset status)
              │                   │                    │
              └─────────┬─────────┘                    │
                        ↓                               │
          AgentBackedEnvironmentalProvider  <────────────┘
          (bounded spatial sampling, nearest-neighbor assignment)
                        │
                        ↓
          Phase 2 Risk Engine (compute_risk) + hazard proxy
                        │
                        ↓
          risk_provider(cell) / hazard_provider(cell)
                        │
                        ↓
          Phase 3 A* routing (UNCHANGED — astar.py, costs.py, grid.py untouched)
                        │
                        ↓
          POST /api/v1/route — structured response
```

## 3. The three agents

| Agent | Wraps | Module |
|---|---|---|
| Weather Intelligence | `app.data.open_meteo_weather.OpenMeteoWeatherAdapter` (Phase 1, unmodified) | `app.agents.weather.agent.WeatherIntelligenceAgent` |
| Oceanographic Intelligence | `app.data.open_meteo_marine.OpenMeteoMarineAdapter` (Phase 1, unmodified) | `app.agents.oceanographic.agent.OceanographicIntelligenceAgent` |
| GIS & Geofencing | `app.gis.{geometry,distance,geofence,grid}` (Phase 2/3, unmodified) | `app.agents.gis.agent.GISGeofencingAgent` |

No agent reimplements Open-Meteo parsing, unit normalization, geometry algorithms, or
Haversine distance — every one of those is imported and called, never rewritten.

## 4. Request/response contracts

`app.models.contracts.AgentResult` — the **verbatim contract from architecture §12**,
never implemented in code until this phase (only `Evidence` and `SafetyGuardResult` were
built in Phases 1-2). Two fields beyond the literal §12 schema, both documented in the
model's own docstring:

- `mode` (architecture §16a's session-type concept, live/demo) — §12 has no such field;
  Phase 4 needs `ORCA_MODE` visible on every result.
- `temporal_validity_status` (the Temporal Validity Gate's VALID/STALE/EXPIRED/
  INVALID_TIMESTAMP/MISSING_TIMESTAMP verdict) — §12's own `temporal_validity` field is a
  `{valid_from, valid_to, is_forecast}` dict (the validity *window*), not the Gate's
  *verdict* on it; the verdict needed a home that doesn't collide with the literal field.

`WeatherIntelligenceAgent.get_weather(latitude, longitude, requested_time=None)` and
`OceanographicIntelligenceAgent.get_marine(...)` both return `AgentResult`.
`GISGeofencingAgent` exposes narrower, purpose-specific methods (`evaluate_point`,
`nearest_hard_geofence_distance_km`, `get_geofences`, `get_static_dataset_status`, ...)
since its outputs are geometric/status objects, not `NormalizedObservation` batches.

## 5. Live provider

Both Weather and Oceanographic agents call their Phase 1 adapter's `fetch()`/`parse()`
unchanged. A successful live call is always `source_tier="live"` (architecture §15 —
independent of `ORCA_MODE`, per §16a's two-independent-concerns rule, exactly as
established in Phase 1/3).

## 6. Cache

`app.agents.common.cache.AgentCache` — Redis-backed, reusing Phase 0's existing client
(`app.services.cache`); no new caching technology. Cache keys are fully deterministic:
`orca:agent:<namespace>:<lat 3dp>:<lon 3dp>:<hour bucket>` — never a random UUID. A
corrupted entry or a Redis outage is always treated as a cache **miss**, never a crash —
caching is best-effort, verified by tests with a simulated Redis outage
(`tests/agents/common/test_cache.py`). Tests never require a real Redis instance (a
`FakeRedis`/`BrokenRedis` test double is used throughout).

## 7. Fallback (3-tier, architecture §16)

```
LIVE ──failure──> CACHED ──miss──> STATIC/DEMO (DEMO mode only) ──unavailable──> structured failure
```

Implemented in `app.agents.common.fallback.fetch_with_fallback` (LIVE→CACHED, shared by
both Weather and Oceanographic agents) plus each agent's own STATIC/DEMO tier
(`app.agents.weather.static_fallback`, `app.agents.oceanographic.static_fallback` — small,
explicitly-labeled synthetic placeholders, `source_tier="synthetic"`).

**Critical safety rule (architecture §16a), enforced structurally**: the STATIC/DEMO
tier is used **only when `ORCA_MODE=demo`**. In `ORCA_MODE=live`, if LIVE and CACHED both
fail, the agent returns `AgentResult(status="failed")` — never silently substitutes
synthetic data. Verified live: `test_live_mode_never_falls_back_to_static` in both agent
test suites.

## 8. Temporal validity

Reused verbatim from Phase 1 (`app.fabric.fabric.ingest`, `app.fabric.temporal.evaluate_temporal_validity`)
— no second implementation. **A cache hit always re-runs the Gate against the current
`requested_time`**, never inheriting its write-time status: data VALID when cached can
correctly become STALE or EXPIRED on a later read. Verified explicitly in
`test_cache_hit_recomputes_temporal_validity_never_inherits_stale_status`.

## 9. Data quality / confidence

Reused verbatim from Phase 2 (`app.reasoning.confidence.compute_confidence`, exact
weights `0.40×freshness + 0.35×completeness + 0.25×agreement`) — no second formula.
`app.agents.common.result.build_agent_result` computes this once, for every agent:
freshness from actual retrieval age vs. the configured max-staleness window,
completeness from the fraction of expected parameters actually present (not missing),
and agreement defaulting to `1.0` — honestly documented as "no known disagreement" (no
second independent source is integrated yet to actually disagree with; architecture
§19/§20 evidence arbitration and conflict resolution remain Phase 4+ future work).

## 10. Provenance

Every `AgentResult.evidence` entry is a real `Evidence` object (architecture §12,
built via `NormalizedObservation.to_evidence()`), carrying source, source_type,
source_tier, timestamps, and the confidence just computed. `spatial_extent` is a GeoJSON
Point. No natural-language explanation is generated anywhere in this phase — that
remains the Evidence & Explanation Agent's job (§28, Phase 6+).

## 11. GIS behavior

`GISGeofencingAgent` wraps Phase 2/3's `app.gis` package. **No real coastline/WDPA/EEZ
data exists** — Phase 1 never acquired Natural Earth, GEBCO, WDPA, or Marine Regions data
(`docs/demo_region.md`). `get_geofences()` returns the same explicit fixture set Phase
3's routing endpoint already used (`app.routing.fixtures.DEMO_FIXTURE_GEOFENCES` —
imported, not duplicated), with metadata (`is_authoritative=False`,
`source_tier="synthetic"`, a `"DEMO DATA / SIMULATION — NOT LIVE DATA"` disclaimer).
`get_static_dataset_status(name)` / `get_bathymetry_status()` **genuinely query** the
Phase 1 `static_layer_sources` registry — gracefully degrading to
`acquisition_status="unknown"` when PostGIS is unreachable (verified live in this
development environment: no Docker, no PostGIS extension available), never fabricating
`"available"`.

## 12. Routing integration (the primary Phase 4 objective)

**Why bounded sampling, not one live call per grid cell**: the demo routing grid is
~1,596 cells (Phase 3, measured). A live call per cell is explicitly disallowed. Instead,
`app.agents.environmental_provider.AgentBackedEnvironmentalProvider` fetches a small,
deterministic `samples_per_axis × samples_per_axis` grid of SAMPLE POINTS (default 4×4 =
16, `Settings.environmental_samples_per_axis`) via the Weather/Oceanographic agents — a
**>100x reduction** in live calls. Every routing grid cell is then assigned its
**nearest sample site's** data via deterministic nearest-neighbor lookup (Phase 2's own
`haversine_km`, reused). This is explicitly **not interpolation** — no in-between value
is invented, and no claim of sub-sample-spacing accuracy is made.

Geometry-based risk factors (`restricted_zone_distance`, `coast_distance`) need no
network call, so they are computed **exactly per grid cell** via the GIS agent, not
sampled. (Documented simplification: no coastline-specific geometry exists yet separate
from the hard-geofence fixture set, so both factors currently derive from the same
nearest-hard-geofence measurement.)

**`app.routing.astar`, `app.routing.costs`, and `app.routing.grid` are completely
unmodified** — the only change is what implements the `EnvironmentalScoreProvider`
Protocol Phase 3 already defined. `POST /api/v1/route` now resolves its providers via
FastAPI dependency injection (`get_gis_agent`, `get_environmental_provider_class`) so the
offline test suite can override them with fast fakes while the live endpoint uses the
real agents by default.

**Missing/failed data policy**: if a sample site's data is unusable
(`AgentResult.status == "failed"` — only reachable in LIVE mode with no live/cached
source), that site is treated as **maximally risky** (`risk_score=1.0`), not zero — an
"unknown is risky, not safe" policy, since Phase 2's Risk Engine itself refuses to score
incomplete inputs (`MissingRiskComponentError`) and A* needs a deterministic numeric
score per cell regardless.

**No official advisory, no cyclone proxy**: architecture §29 does not require Phase 4 to
implement official-advisory ingestion, and `cyclone_proxy` needs signals (pressure
tendency, gusts, spatio-temporal persistence) Phase 1's adapters do not fetch. Both are
honest, documented scope limitations — `advisory_or_hazard_risk("none")` is used, and
`hazard_score` is `lightning_thunderstorm_proxy(weathercode)` only (reused from Phase 2,
not a new hazard framework).

## 13. Risk integration

The Phase 2 Risk Engine is authoritative, unchanged: same weights (wave 0.25, wind 0.15,
advisory/hazard 0.20, lightning proxy 0.10, restricted distance 0.15, coast distance
0.10, data confidence 0.05), same thresholds (LOW<0.33, MODERATE<0.66, HIGH≥0.66),
loaded from the same `risk_weights.yaml`. `app.agents.environmental_provider._site_risk_and_hazard`
builds a `NormalizedRiskComponents` from real weather/marine data and geometry, then
calls `compute_risk()` — the exact same function Phase 2 shipped and tested. No
"Weather Agent Risk Score" or "Ocean Agent Risk Score" exists as a competing system.

## 14. Demo mode

`RouteResult.data_quality` is derived from whether **any** sample site actually fell back
to synthetic data (`AgentBackedEnvironmentalProvider.used_synthetic_fallback`) —
independent of `ORCA_MODE`, since a genuine live Open-Meteo call is real data regardless
of session type (the same two-independent-concerns discipline established in Phase 1/3).
Static/demo agent fallbacks always carry a `"DEMO DATA / SIMULATION — NOT LIVE DATA"`
warning string.

## 15. Configuration

Added to `backend/app/config.py` (same centralized-config pattern as Phases 1-3):
`weather_cache_ttl_seconds` (1800), `marine_cache_ttl_seconds` (1800),
`gis_cache_ttl_seconds` (86400), `environmental_samples_per_axis` (4),
`max_concurrent_agent_requests` (16). No new secrets, no new API keys — Open-Meteo still
requires none.

## 16. Limitations

- **Sequential-request latency is real and was measured, not assumed**: fetching a 3×3
  sample grid (18 HTTP calls) sequentially took **~98 seconds** in this development
  environment — each Open-Meteo call averaged ~5s, far slower than the sub-second calls
  seen in Phase 1's isolated live tests, likely due to this sandbox's network path or
  request pacing. This made the naive sequential design impractical for a synchronous
  HTTP endpoint.
- **Mitigation implemented, also measured**: fetching is parallelized via a bounded
  `ThreadPoolExecutor` (`Settings.max_concurrent_agent_requests`, default 16 — I/O-bound
  work, so higher concurrency is safe here). Measured improvement: the same 18-call
  workload dropped from ~98s to ~11s at concurrency=16; the **default** configuration
  (16 sample points = 32 calls) measured **~12.2s** end-to-end, confirmed via a real
  `POST /api/v1/route` call (12.56s wall time, HTTP 200, correct varying per-cell risk
  scores in the response). This is still slow for an HTTP endpoint but within typical
  client timeout tolerances; a production deployment closer to Open-Meteo's network, or
  using its native multi-location batch parameter (not implemented here — a legitimate
  further optimization, deliberately deferred to keep Phase 4's diff to Phase 1's
  adapters at zero), would be expected to do meaningfully better.
- No official advisory ingestion (architecture §29, not required this phase).
- No `cyclone_proxy` wiring into routing hazard (needs data Phase 1 doesn't fetch —
  pressure tendency, gusts, persistence across time steps).
- `coast_distance` and `restricted_zone_distance` currently share one geometry
  measurement (no separate coastline dataset exists).
- No evidence arbitration / conflict resolution (architecture §19-20) — only one source
  per domain exists (Open-Meteo), so "agreement" is always the honestly-labeled default
  `1.0`, not a verified cross-source consistency check.

## 17. Unavailable static datasets

`static_layer_sources` (Phase 1 registry) still shows all four named datasets
(`natural_earth_coastline`, `gebco_bathymetry`, `wdpa_protected_areas`,
`marine_regions_eez`) as `not_acquired` — Phase 4 did not acquire any of them (out of
scope; see `docs/demo_region.md`). `GISGeofencingAgent.get_static_dataset_status()` was
verified live against this development environment's unreachable PostGIS instance and
correctly returned `acquisition_status="unknown"` (DB unreachable), never a fabricated
answer.

## 18. Testing

219 → 270 → **347** tests total across Phases 1-4 (270 through Phase 3, +77 this phase:
76 in `backend/tests/agents/` + 1 new API test). `pytest -m "not integration and not
live"` (340 tests) requires no network access, no Redis, and no database — every
Weather/Oceanographic agent test uses `respx`-mocked HTTP and a `FakeRedis`/`BrokenRedis`
test double; every routing-integration test uses stubbed agents. `pytest -m live` (3
tests, unchanged from Phase 1) is the real Open-Meteo regression. `pytest -m integration`
(4 tests, unchanged) requires PostgreSQL/PostGIS/Redis — unavailable in this development
environment (Docker not installed, local PostgreSQL has no PostGIS extension), reported
as **FAIL**, never faked.

A real, non-network-dependent bug was found and fixed during this phase's development:
mocked test payloads copied from Phase 1's isolated `parse()`-only tests used far-future
(2099) timestamps, which worked fine for testing normalization in isolation but broke
once these Phase 4 tests exercised the *full* Temporal Validity Gate (the Gate correctly
reported `EXPIRED` against a `requested_time` in 2026 for data valid in 2099). Fixed by
anchoring all such fixtures to real wall-clock time, then further hardened against
hour-boundary cache-key flakiness discovered by literally hitting it in a live test run
(a module anchored at `11:56` pushed a `+45min` offset across an hour boundary,
genuinely breaking the cache-key lookup) — see the git-history-equivalent narrative in
this document's own drafting; the final fixtures use either same-timestamp calls (where
staleness isn't the point) or fully-synthetic fixed timestamps (where precise staleness
control is the point), eliminating wall-clock coupling entirely.

## 19. Architecture compliance

- Three named agents match architecture §10 exactly (Weather Intelligence, Oceanographic
  Intelligence, GIS & Geofencing) — no new agent roles invented.
- None is an LLM call, matching §10's own table.
- No LangGraph, no orchestration graph — these remain deterministic service classes,
  callable directly, ready for LangGraph to wrap in a later phase.
- No CrewAI, no alternative orchestration framework.
- No new database — Redis (already in the architecture) is used for caching only;
  PostgreSQL/PostGIS schema is unchanged from Phase 1.
- Phase 2's Risk Engine weights/thresholds are byte-identical, reused not reimplemented.
- Phase 3's A* algorithm, cost function, corner-cutting rule, and no-route semantics are
  completely unmodified — only the provider boundary changed, exactly as Phase 3's own
  report anticipated.
- Demo/live data distinction preserved and enforced structurally throughout (§16a).
- Lightning proxy terminology discipline preserved (§29b) — `lightning_thunderstorm_proxy`,
  never a claim of real-time strike detection.
