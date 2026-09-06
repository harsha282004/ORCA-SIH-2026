# Phase 3 — Fishing Intelligence Report

## 1. Executive Summary

Phase 3 turns ORCA's existing single-point Risk/Suitability engines into genuine multi-candidate fishing decision support: discover ranked candidate areas, find the nearest one that actually passes safety filtering, compare specific areas, and evaluate one area across real forecast hours. Everything is composed from the SAME deterministic engines every other ORCA surface already uses — no new risk/suitability/safety formula exists anywhere in this phase. A real, pre-existing limitation in the single-value weather/marine agents was found and correctly worked around (not silently ignored) while building temporal intelligence — documented in §9. Ask ORCA now genuinely answers "find suitable fishing areas near X" with a Groq explanation grounded in real ranked candidates, verified live end-to-end. Official INCOIS PFZ remains, correctly, unavailable everywhere.

## 2. Existing Suitability Capability (audited before writing anything)

Before Phase 3: `RiskSuitabilityAgent.evaluate()` (Phase 5) already existed and was already used by both `POST /api/v1/query`'s single-point graph node and `GET /api/v1/layers/suitability`'s per-sample-point map layer. Its `signal_score = 1.0 - risk_score` is an explicitly documented placeholder — the engine's own docstring already says "No independent SST/chlorophyll-favorability model or real PFZ proximity exists yet... using the inverse of the risk score as a conservative placeholder signal is an HONEST, DOCUMENTED limitation." **This means chlorophyll, GEBCO bathymetry, and INCOIS SST were NOT, and still are not, inputs to the deterministic suitability score** — only wave, wind, geofence-distance, and confidence (the Risk Engine's own 7 components) drive it. Phase 3 did not change this — it would have required inventing a new formula, explicitly disallowed. What Phase 3 added is the ability to run this SAME evaluation over many points instead of one, and to rank/filter/compare the results.

Also already existing: `make_decision`/`evaluate_safety_guard`/`derive_safety_facts` (the exact safety-precedence chain), the Phase 1 chlorophyll/SST/GEBCO data foundation, and `parse_hourly_timeseries` (built in Phase 1 for the map's time slider, reused here for real reasons — see §9).

## 3. Fishing Intelligence Architecture

```
Query ("Find suitable fishing areas near Mangaluru")
    |
    v
LangGraph (UNCHANGED) — query_understanding node classifies intent_class
    |                     (this label already existed: "zone_recommendation")
    v
app/api/v1/query.py — AFTER the graph run, if intent_class == "zone_recommendation":
    |
    v
app.fishing.engine.generate_candidates()
    - bounded sample grid (app.agents.environmental_sampling, same strategy as the map's suitability layer)
    - per candidate: RiskSuitabilityAgent.evaluate() -> derive_safety_facts -> evaluate_safety_guard -> make_decision
      (the IDENTICAL three-step pipeline app.orchestration.nodes runs for one point, looped over many)
    |
    v
rank_candidates() — safety precedence: only Decision RECOMMEND/RECOMMEND_WITH_CAUTION candidates are ranked;
                     everything else lands in `avoid` with its real reason, never silently dropped
    |
    v
Evidence (DecisionProvenanceGraph, built from the top-ranked candidate's real Risk/Suitability/Safety/Decision output)
    |
    v
Groq (app.agents.evidence_explanation.agent.EvidenceExplanationAgent — SAME grounding-checked agent, SAME LLM call
      every other query type uses) — explains the deterministic result, never invents it
    |
    v
Natural-language response + the full ranked/avoid candidate list, returned to the caller
```

This is deliberately **not** a new LangGraph node — see §3a.

### 3a. Why the graph itself was not modified

The existing graph is topologically single-point (`query_understanding -> [weather, oceanographic, gis] -> risk_suitability -> safety_guard -> decision -> evidence`, all operating on ONE resolved lat/lon). Multi-candidate ranking is a different computation SHAPE that graph cannot express without new nodes/edges. Rather than modify the graph's proven topology, the composition happens at the API-handler level in `app/api/v1/query.py`, using the exact same pattern `POST /api/v1/route` already established (a deterministic engine invoked directly from an HTTP handler, entirely outside the graph). The graph itself still runs unmodified and still performs its own single-point analysis on the query's resolved location for every query, including zone_recommendation ones (a small, accepted redundancy — see §20); only the RESPONSE is overridden with the genuinely multi-candidate deterministic result when the intent calls for it.

## 4. Data Sources

| Variable | Source | Representation | Resolution | Temporal Semantics | Coverage |
|---|---|---|---|---|---|
| Wave height/direction, wind speed, SST, current velocity | Open-Meteo | live bounded sample grid (6×6=36 candidates by default) | ~250m×450m per candidate cell at the demo bbox's scale | Real hourly forecast (see §9 for the exact per-hour mechanism) | full demo bbox |
| Geofence distance/boundary | GIS fixture (`app.routing.fixtures`) | exact polygon geometry | n/a | static | full demo bbox |
| GEBCO bathymetry, INCOIS chlorophyll, INCOIS SST | Phase 1 acquired samples | 225/51/56 sparse points | see Phase 1 report | static/no-hourly-dimension | NOT used as candidate inputs (see §2) |
| Official INCOIS PFZ | — | — | — | — | UNAVAILABLE (§15) |

## 5. Fishing Suitability Method

For each candidate point: `app.suitability.engine.evaluate_suitability(signal_score=1-risk_score, risk_score, distance_to_zone_km, confidence, weights)` — the EXACT Phase 2 formula, EXACT frozen weights (`suitability_weights.yaml`). The risk score behind it comes from `app.risk.engine.compute_risk` over the 7 frozen components (wave, wind, advisory, lightning-proxy, restricted-zone-distance, coast-distance, confidence-penalty) — `risk_weights.yaml`, unchanged. **Only wave, wind, and geofence-distance are genuinely used per candidate**; chlorophyll/bathymetry/INCOIS SST are shown as informational `environmental_context` on each candidate (real values, real timestamps) but are explicitly, honestly NOT suitability-score inputs (`suitability_signal_is_risk_proxy: true` on every candidate, and the report says so plainly rather than implying otherwise).

## 6. Candidate Generation

`app.fishing.engine.generate_candidates()` reuses `app.agents.environmental_sampling.sample_environment_grid` (the exact bounded sampling `GET /api/v1/layers/suitability` already used, extracted to a shared module this phase so both consumers use one implementation — see §19). Default: 6×6 = 36 points across the full `DEMO_BBOX` (never invented, never modified). Each point independently evaluated; every candidate — ranked or avoided — is retained and returned, never silently dropped.

## 7. Ranking

`rank_candidates()`: a candidate is eligible for ranking ONLY if its Decision outcome is `RECOMMEND`/`RECOMMEND_WITH_CAUTION` (i.e. the Safety Guard passed). Eligible candidates are then sorted by suitability score, descending, and assigned `rank`. Optional `min_suitability`/`max_risk` query parameters filter further, moving anything below/above the threshold into `avoid` with an explicit reason. Verified live: a real point inside the demo geofence, with a raw suitability score of 0.83 (HIGH), was correctly excluded from ranking and placed in `avoid` with reason "Safety Guard blocked this query: BLOCK_BOUNDARY" — proof safety precedence is enforced by construction, not by sorting.

## 8. Safety Precedence

Implemented exactly as required: SAFETY (Safety Guard) → GEOGRAPHIC (hard geofence, folds into Safety Guard's `BLOCK_BOUNDARY`) → RISK (Decision Engine's HIGH-risk verdict) → SUITABILITY (ranking) → PREFERENCE/DISTANCE (only used to break ties for "nearest suitable"). None of this is new logic — `make_decision`/`evaluate_safety_guard` already encode this hierarchy; Phase 3 calls them per-candidate instead of once.

## 9. Temporal Fishing Intelligence

**A real, pre-existing limitation was found and correctly handled, not silently ignored.** `WeatherIntelligenceAgent.get_weather(requested_time=...)`/`OceanographicIntelligenceAgent.get_marine(requested_time=...)` — used everywhere else in the system, including Phase 2's map time slider — do NOT actually select the requested hour's forecast value; their underlying `parse_hourly_observations` always resolves the hour nearest the live fetch's own wall-clock time (`raw.retrieved_at`), regardless of `requested_time`. `requested_time` genuinely affects the cache key and the staleness/confidence computation, but not which value comes back. This was discovered live while building `/fishing/temporal` (looping `evaluate_candidate` over several `requested_time` values produced byte-identical wave/wind/SST across hours). Confirmed and precisely traced. It was **not fixed** in this phase — it's foundational, widely-used code, and changing it is out of Phase 3's scope and carries real regression risk. Instead, `app.fishing.temporal.evaluate_temporal_suitability` reuses the OTHER already-real multi-hour path — `parse_hourly_timeseries` (Phase 1's own genuine 24-hour series function) — fetched ONCE, and computes risk/suitability directly from the same low-level deterministic component functions (`wave_risk`, `wind_risk`, `lightning_thunderstorm_proxy`, `compute_risk`, `evaluate_suitability`) at the SAME frozen weights. Verified live: 6 real hours showed genuinely distinct wave height (1.48→1.42m), wind speed (6.08→4.75 m/s), and SST (28.6→28.3°C), with suitability correctly tracking risk. Confidence per hour uses one documented constant (0.85) since Open-Meteo exposes no per-hour uncertainty figure — never a fabricated precision curve.

## 10. Fishing Page

New `/fishing` (`frontend/src/routes/FishingPage.tsx`). DISCOVER: a ranked candidate list ("Best Available Areas") fed by `GET /api/v1/fishing/candidates`, rendered on the same MapLibre+deck.gl map (`buildFishingCandidatesLayer` — green=ranked, red=avoid, sized by rank). ANALYZE: clicking any candidate (list or map) opens the existing `EvidencePanel`, extended with a `fishing-candidate` view showing score, risk, safety, real risk factors, and environmental context. COMPARE: selecting 2 areas calls `POST /api/v1/fishing/compare` and shows the real deterministic reason. A search box reuses the EXISTING `POST /api/v1/query` (Ask ORCA's own endpoint, not a new one) — verified live producing a real, grounded, non-fallback explanation.

## 11. Marine Map Integration

`/marine-map` gained one new toggle, "Fishing Candidate Areas" (Fishing group), backed by the SAME `GET /api/v1/fishing/candidates` fetch and the SAME `buildFishingCandidatesLayer` — no second implementation. Verified live: toggling it on renders real ranked/avoid candidates alongside the map's existing risk/geofence/bathymetry/chlorophyll layers with no regression to any of them.

## 12. Ask ORCA Integration

Verified live end-to-end: `"Find suitable fishing areas near Mangaluru"` → classified `zone_recommendation` (the LLM's own existing system prompt already lists this intent class, unchanged) → 36 real candidates generated, 30 ranked, 6 correctly avoided → Groq produced a real, grounded, non-fallback explanation (`used_fallback_template: false`) referencing the actual deterministic numbers (risk 0.144 LOW, suitability ≈0.85). The LLM never computed the recommendation — the response's `decision`/`fishing_candidates.top` fields are 100% deterministic, and the grounding check (`app.agents.evidence_explanation.grounding`, unchanged) still gates the explanation before it's trusted.

## 13. Evidence & Provenance

Every candidate carries `source`, `timestamp`, real `risk_factors` (name/normalized_value/weight/contribution, straight from `RiskResult.factors`), and `environmental_context`. The Ask ORCA zone_recommendation path builds a real `DecisionProvenanceGraph` from the top candidate (reusing the EXISTING `RiskProvenance`/`SuitabilityProvenance`/`Decision`/`SafetyGuardResult` models unchanged) and persists it to the existing `ProvenanceStore`, exactly like every other query type — `GET /api/v1/query/{query_id}/provenance` works unchanged for a fishing-zone-recommendation turn too.

## 14. Confidence / Data Sufficiency

`data_confidence_penalty_risk` (an existing risk component) already penalizes low confidence into the risk score itself. Separately, every candidate exposes its own `confidence` (from the weather/marine agents' real freshness/completeness computation) alongside the suitability score — never conflated. A candidate whose weather/marine data was unusable is returned with `status: "insufficient_data"` and `suitability_score: null` (never a guessed/zero value) — verified via `test_insufficient_data_status_when_weather_failed`.

## 15. PFZ Limitation

Unchanged from Phase 1/2: no official machine-readable INCOIS PFZ geometry exists anywhere in this integration. Every fishing endpoint's `meta.pfz_status` (or `suitability.pfz_reference_status`) reads `"unavailable"`. The frontend's PFZ toggle is rendered **Locked** (never a functional-looking checkbox) on both `/fishing` and `/marine-map`. No PFZ polygon, fake or otherwise, exists anywhere in this codebase.

## 16. Testing

**Backend**: `pytest -q` → **556 passed, 2 failed**. Both failures are the SAME pre-existing/environment-dependent issues documented in the Phase 1/2 reports (Groq-configured LLM test; the gis-agent test whose "no live PostGIS" premise is false in this running environment) — zero new regressions. 19 new Phase 3 tests (`tests/fishing/test_engine.py`: 11, `tests/api/test_fishing.py`: 8), covering determinism/reproducibility, safety-precedence exclusion, insufficient-data handling, ranking with filters, nearest-suitable, comparison (including "no preference" when all candidates are blocked), and API-level validation (out-of-domain, invalid compare size).

**Frontend**: `tsc -b` → PASS. `eslint .` → PASS (0 errors, 0 warnings). `npm run build` → PASS (same pre-existing deck.gl chunk-size advisory, non-blocking). No new test framework introduced (none existed before Phase 3 either — see Phase 2's own report for why); verification continues via typecheck/lint/build/E2E.

**E2E (live browser)**: `/fishing` loads, real candidates render on the map (green/red, correctly clustered), "Best Available Areas" populates with 6 real ranked areas, Compare Areas produces a real deterministic reason, the search box gets a real grounded Ask ORCA answer, clicking a map candidate opens the evidence panel with real factors. `/marine-map`'s new toggle renders real candidates with no regression to existing layers. `/route-planner` unchanged: exactly one real route POST, FEASIBLE result. Zero console/page errors across every run.

## 17. Docker

All 4 services healthy throughout (`docker compose ps`, `/health`, `/api/v1/health/ready` all verified after every rebuild). The same Redis dataset-status cache staleness documented in the Phase 2 report recurred once more this session (after a Docker restart) — flushed manually again; still unresolved technical debt, not touched this phase per its own "do not redesign Redis" instruction.

## 18. Performance

Candidate generation (36 points) takes ~13s live (bounded concurrency, mostly Open-Meteo fetches — the SAME cost profile the map's own suitability layer already has). `/fishing/compare` (2-5 explicit points) and `/fishing/temporal` (one point, one real 24h fetch) are both fast (~3s). No live call is made per candidate for GEBCO/INCOIS — those remain acquired-snapshot reads from disk, untouched. Ask ORCA's zone_recommendation path still runs the graph's own single-point analysis in addition to the fishing engine (a real, accepted redundancy — see §20).

## 19. Files Changed

**New**: `backend/app/fishing/{__init__,models,engine,temporal}.py`, `backend/app/api/v1/fishing.py`, `backend/app/agents/environmental_sampling.py`, `backend/tests/fishing/*`, `backend/tests/api/test_fishing.py`, `frontend/src/routes/FishingPage.tsx`, `docs/PHASE_3_FISHING_INTELLIGENCE_REPORT.md`.

**Modified**: `backend/app/api/v1/layers.py` (now imports the shared sampling helper instead of a private local copy), `backend/app/suitability/engine.py` (`classify_suitability_category` relocated here from the API layer, so both map layers and the fishing engine share one definition), `backend/app/api/v1/query.py` (zone_recommendation response override), `backend/app/main.py` (fishing router registered), `frontend/src/lib/api.ts` (fishing types/clients), `frontend/src/components/map/mapLayers.ts` (`buildFishingCandidatesLayer`), `frontend/src/components/map/EvidencePanel.tsx` (fishing-candidate view), `frontend/src/routes/MarineMapPage.tsx` (candidates toggle), `frontend/src/App.tsx`, `frontend/src/components/layout/Navbar.tsx`.

## 20. Known Limitations

- **The single-value weather/marine agents' `requested_time` doesn't select the requested hour** (§9) — a real, pre-existing, foundational-code property, worked around for temporal fishing intelligence but NOT fixed system-wide. This likely also means Phase 2's map time slider changes the CACHE KEY and confidence/staleness computation per hour, but may not change the underlying wave/wind/SST VALUE the way its own report implied — flagged here for anyone building on the time slider next.
- **Ask ORCA's zone_recommendation path still runs the graph's own single-point analysis** on the resolved centroid, in addition to the fishing engine, before its result is overridden — a real, accepted inefficiency (one extra risk_suitability/safety/decision evaluation per fishing query) rather than risk modifying the graph's proven topology.
- **Candidate grid resolution (6×6=36) is a deliberate, bounded choice**, not a fundamental limit — increasing it is possible but was not attempted, to avoid unnecessary load per this phase's own "don't hammer external services" instruction.
- **Chlorophyll/bathymetry/INCOIS SST are not suitability-score inputs** (§2/§5) — an existing (Phase 2-era) architectural fact, not something Phase 3 introduced or could fix without inventing a new formula.
- The Redis cache-staleness issue from Phase 2 (§17) remains open technical debt.

## 21. Phase 4 Readiness

**Yes, conditionally.** The fishing-intelligence foundation (candidate generation, ranking, safety precedence, comparison, temporal evaluation) is real, tested, and verified live end-to-end, including through Ask ORCA. Before Phase 4 (hazard/alert intelligence) builds on this: (1) be aware of §9's `requested_time` finding — any new hazard feature needing genuine per-hour values should use the `parse_hourly_timeseries` pattern `app.fishing.temporal` established, not the single-value agents' `requested_time` parameter; (2) the Redis cache-staleness issue should ideally be resolved (or at minimum, its manual-flush workaround automated) before more features come to depend on `static_layer_sources` status checks.
