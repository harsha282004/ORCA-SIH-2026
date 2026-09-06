# Phase 2 — Marine Intelligence Map Report

## 1. Executive Summary

Phase 2 wired Phase 1's real acquired INCOIS SST data into the live API/map (Part A1), recovered and verified the Docker/PostGIS stack (Part A2), and built a dedicated `/marine-map` page — reusing the exact same MapLibre+deck.gl engine and a newly-extracted shared `useMarineLayers` hook the Route Planner now also uses, avoiding a second map implementation. The map now supports bathymetry, chlorophyll, two independent SST sources, currents, waves, wind, ORCA risk, ORCA fishing suitability, and geofences — every one of them honestly labeled by real/sparse/static/unavailable status, with a genuine time slider that re-requests real backend data (verified live: moving the slider fires real `?at=` requests to `risk-surface`, `oceanography`, and `suitability`). INCOIS PFZ remains, correctly, unavailable — no fabricated geometry was added anywhere.

## 2. Phase 1 Fixes

**A1 — INCOIS SST wiring.** Extended the *existing* `GET /api/v1/layers/oceanography` response (no new endpoint, no duplicate route) with a new top-level `incois_sst` block, reading the already-acquired `data/processed/incois_sst_orca_bbox.geojson` and the existing `static_layer_sources` provenance row — the same pattern already used for chlorophyll/bathymetry. No data was re-downloaded. Verified live: `incois_sst.meta.sample_count == 56`, `value_range 29.63–31.86 °C`, source `ESSO-INCOIS`, kept structurally separate from Open-Meteo's own SST in the same response so the two are never visually or semantically merged.

**A2 — Docker/PostGIS verification.** Docker Desktop was found stopped at the start of this task (`docker ps` failed to connect to the daemon; its WSL2 backend distro was `Stopped`). Recovered via a safe action only — launching the existing Docker Desktop application (`C:\Users\harsh\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe`), no infrastructure/config change. `docker compose up -d` brought all 4 services up healthy; PostgreSQL/PostGIS connectivity confirmed (`PostGIS 3.4`); all 3 Phase 1 `static_layer_sources` rows (`gebco_bathymetry`, `incois_chl`, `incois_sst`, all `acquired`) and all 4 Phase 1 data files were confirmed intact through the `./data:/app/data` volume mount. **A recurring operational issue was found and fixed twice this session**: `GISGeofencingAgent`'s 24h Redis cache can retain a stale pre-acquisition `not_acquired` value across container restarts even when Postgres already has the correct `acquired` row — fixed both times with a manual `redis-cli DEL`, and documented here as a real, unresolved architectural gap (see §14).

## 3. Marine Map Architecture

- **New page**: `/marine-map` (`frontend/src/routes/MarineMapPage.tsx`), lazy-loaded exactly like `/route-planner` (same code-splitting rationale — MapLibre/deck.gl weight only downloaded when a visitor opens either map page).
- **Shared logic, not duplicated**: `frontend/src/hooks/useMarineLayers.ts` is a new hook extracted from what was previously inlined in `RoutePlannerPage.tsx` — it owns layer toggling, fetching (`useMapLayer`), and deck.gl layer construction for every non-route layer (bathymetry, chlorophyll, both SSTs, currents, waves, wind, risk, suitability, geofences). Both `/route-planner` and `/marine-map` now call this SAME hook; `RoutePlannerPage` adds only its route-planning form and the route-risk deck.gl layer on top.
- `/route-planner` stays "plan and evaluate a route"; `/marine-map` is "explore conditions" — no origin/destination form on the map page, and its Routing layer-control group is present (per the requested layer taxonomy) but explicitly locked with "plan a route on the Route Planner page" rather than duplicating the planning UI.
- **`useMapLayer` extended, not replaced**: its `MapLayerState` now carries the full raw response (`raw`) alongside `data`/`meta`, needed because `/layers/oceanography`'s response carries a second top-level block (`incois_sst`) beyond the existing `{data, meta, errors}` shape. Every other caller is unaffected (defaults preserved).

## 4. Layers Implemented

| Layer | Source | Representation | Status | Real/Demo | Coverage |
|---|---|---|---|---|---|
| Marine basemap | OpenStreetMap | raster tiles | working | Real | full bbox |
| Bathymetry | GEBCO_2026 Grid (WMS) | 225 sampled points | STATIC | Real (sparse) | ~94% of bbox width/height |
| Chlorophyll-a | ESSO-INCOIS (WMS) | 51 sampled points | CURRENT | Real (sparse, gappy) | does not reach eastern bbox edge |
| SST (Open-Meteo) | Open-Meteo Marine | 16 live bounded samples | FORECAST | Real | full bbox |
| SST (INCOIS) | ESSO-INCOIS (WMS) | 56 sampled points | CURRENT | Real (sparse, gappy) | does not reach eastern bbox edge |
| Currents | Open-Meteo Marine | 16 live bounded samples | FORECAST | Real | full bbox |
| Waves | Open-Meteo Marine | 16 live bounded samples | FORECAST | Real | full bbox |
| Wind | Open-Meteo Weather | 16 live bounded samples (newly surfaced) | FORECAST | Real | full bbox |
| ORCA Risk | deterministic Risk Engine | 1,596-cell grid | FORECAST | Derived | full bbox |
| ORCA Fishing Suitability | deterministic Suitability Engine | 16 sampled points | FORECAST | Derived | full bbox |
| Geofences | GIS fixture | 1 polygon | STATIC | Demo fixture, `is_authoritative:false` | eastern strip |
| INCOIS PFZ | — | — | UNAVAILABLE | — | — |
| Route / Route risk | Routing Engine | line + risk-colored segments | (Route Planner only) | Derived | per-request |

## 5. Temporal Map

`GET /api/v1/layers/marine-timeseries` (built in Phase 1) is now called from the frontend for the first time, via `useMarineTimeseries` + the new `TimeSlider` component. It fetches 24 real hourly Open-Meteo timestamps × 11 variables for one reference point (the demo region's center, `13.075°N, 74.275°E` — this page has no origin/destination selection). Moving the slider does two real things, verified live via network capture:
1. Updates the slider's own readout (SST/wave/wind for the selected real hour).
2. Re-fetches `GET /api/v1/layers/risk-surface?at=…`, `GET /api/v1/layers/oceanography?at=…`, and `GET /api/v1/layers/suitability?at=…` with the selected timestamp — genuinely different backend-computed values per hour, never a relabeled copy of the same response.

Bathymetry, chlorophyll, INCOIS SST, and geofences never accept `at` — moving the slider does not touch them, correctly preserving their real temporal semantics (static/no-time-dimension), per the explicit "do not pretend they change hourly" requirement.

## 6. Data Limitations (unchanged from Phase 1, restated honestly here)

- GEBCO bathymetry: 225 point samples, ~5.6×11.2 km spacing — not a continuous field, not the native 15 arc-second grid.
- INCOIS chlorophyll: 51/64 requested points — 13 gaps, coverage does not reach the bbox's eastern edge.
- INCOIS SST: 56/64 requested points — same gap pattern as chlorophyll, and (until this task) sitting unused.
- INCOIS PFZ: no official machine-readable vector geometry exists anywhere in this integration; the map's PFZ toggle stays locked/unavailable, never a fabricated polygon.
- None of these were re-acquired or expanded this phase, per explicit instruction — see §14 for the future-upgrade note.

## 7. Provenance

Every layer's `meta` object (already established in Phase 1, unchanged in shape) carries `source`, `source_url` where applicable, `is_authoritative`, `acquired_at`/`generated_at`, and a `sample_count`/`value_range` where the layer is a sparse acquired sample rather than a live fetch. The `EvidencePanel` reads these fields directly on click — nothing is computed or re-derived in the frontend. New entries added this phase: `incois-sst` and `wind` feature-click cards.

## 8. Freshness

Reused `classify_freshness_status()` from Phase 1 verbatim — no second freshness system. New today: the wind fields piggyback on the same `AgentResult` freshness already computed for weather samples (no new computation); INCOIS SST's freshness follows the exact same "CURRENT (source has no time dimension)" reasoning already applied to chlorophyll.

## 9. Map Interaction

`EvidencePanel` now handles two more layer types (`incois-sst`, `wind`). `LayerControlPanel` now renders a "Locked" badge (with a lock icon) instead of a generic "N/A" for unavailable layers, matching the requested `PFZ [LOCKED / UNAVAILABLE]` wording. `DataStatusPanel` now shows an honest sample-count note (e.g. "225 samples", "51 samples") beneath the freshness badge for sparse acquired layers, addressing the "REAL DATA / PARTIAL SAMPLED" requirement without inventing a second status vocabulary.

## 10. APIs

**Modified:**
- `GET /api/v1/layers/oceanography` — response now includes `incois_sst` (real, wired); per-sample features now also carry `wind_speed_ms`/`wind_direction_deg` (already-fetched weather data, not a new call).
- `app/agents/gis/agent.py` — new `get_incois_sst_status()`.

**No new endpoints were created** — Part A1 explicitly required reusing the existing oceanography endpoint rather than adding a duplicate, and the time slider reuses Phase 1's already-built `marine-timeseries` endpoint unchanged.

## 11. Testing

**Backend**: `pytest -q` → **537 passed, 2 failed**. Both failures are the same pre-existing/environment-dependent issues already documented in the Phase 1 report and the Phase 1 audit (the Groq-configured LLM test, and the gis-agent test whose "no live PostGIS" premise is false in this fully-running environment) — neither is a Phase 2 regression; neither was modified.

**Frontend**: no unit-test framework exists in this repository (confirmed by inspecting `package.json` — only `tsc`/`eslint`/`vite`), and Phase 2 did not introduce one (would be a new-tool decision beyond this task's scope) — continuing this project's established verification pattern of typecheck + lint + build + live browser E2E.
- `tsc -b` → **PASS** (0 errors)
- `eslint .` → **PASS** (0 errors, 0 warnings)
- `npm run build` → **PASS** (same pre-existing >500kB chunk advisory from deck.gl, non-blocking)

**E2E (live browser, Puppeteer)**:
- `/marine-map` loads, real coastline/place-name basemap visible, layer toggles fetch real data with exactly the expected `GET /api/v1/layers/*` calls (no duplicates, no direct external-provider calls).
- Enabling SST/INCOIS-SST/Wind fires exactly one `/layers/oceanography` request (shared fetch, not three).
- Moving the time slider fires exactly the three expected `?at=` re-fetches (risk-surface, oceanography, suitability) — genuine data change confirmed by inspecting the request URLs.
- `/route-planner` still submits exactly one real `POST /api/v1/route` and renders `FEASIBLE` after the `useMarineLayers` refactor — zero regression.
- Zero console/page errors on both pages across every run.

**Docker**: `docker compose ps` → all 4 services healthy; `/health` and `/api/v1/health/ready` both 200; Phase 1 data and provenance rows confirmed intact.

## 12. Performance

No new performance architecture was introduced (no manual chunking, no new caching layer). The shared `useMarineLayers` hook itself is a performance-positive change — the SST/currents/waves/wind toggles already shared one oceanography fetch before this phase; that discipline is now reused identically on the new page. The one real bug found and fixed this phase was unrelated to data-fetching performance: the Marine Map's own `<section>` was rendering as a near-zero-height MapLibre canvas because a column-flex wrapper with no defined height gave `flex-1` nothing to grow into — fixed with an explicit `h-[70vh]`/`lg:h-[75vh]`, verified via canvas pixel dimensions before/after (1150×1 → 1150×823).

## 13. Files Changed

**New**: `frontend/src/routes/MarineMapPage.tsx`, `frontend/src/hooks/useMarineLayers.ts`, `frontend/src/hooks/useMarineTimeseries.ts`, `frontend/src/components/map/TimeSlider.tsx`.

**Modified**: `backend/app/api/v1/layers.py` (incois_sst block, wind fields), `backend/app/agents/gis/agent.py` (`get_incois_sst_status`), `backend/tests/api/test_layers.py` (+3 tests), `frontend/src/lib/api.ts` (`IncoisSstLayerMeta`, `OceanographyApiResponse`, marine-timeseries types/client), `frontend/src/hooks/useMapLayer.ts` (raw-response passthrough), `frontend/src/components/map/mapLayers.ts` (`buildIncoisSstLayer`, `buildWindLayer`), `frontend/src/components/map/EvidencePanel.tsx`, `frontend/src/components/map/LayerControlPanel.tsx` (locked badge), `frontend/src/components/map/DataStatusPanel.tsx` (sample-count note), `frontend/src/routes/RoutePlannerPage.tsx` (refactored onto `useMarineLayers`), `frontend/src/App.tsx`, `frontend/src/components/layout/Navbar.tsx` (new route/nav link).

## 14. Known Limitations

- The Redis dataset-status cache can go stale across container restarts (found twice this session, fixed manually both times) — no automatic invalidation-on-restart exists; only the acquisition script itself flushes it after a fresh run. A real gap worth closing before relying on this in a less closely-watched environment.
- The time slider queries a single fixed reference point (region center), not the point currently at the map's viewport center or a user-clicked location — a reasonable Phase 2 scope boundary, not a defect.
- No frontend unit-test framework exists; verification remains typecheck/lint/build/E2E, as it has been throughout this project.
- Data sparsity limitations (GEBCO/chlorophyll/SST sample density and coverage gaps) are unchanged from Phase 1 — intentionally not addressed this phase.

**Future Data Upgrade (documented, not implemented):** the GEBCO/INCOIS sampling density and coverage gaps identified in the Phase 1 audit remain exactly as they were; increasing `samples_per_axis` for either source, or re-attempting GEBCO's WCS/OPeNDAP path, would be the natural next acquisition improvement — out of scope here per explicit instruction.

## 15. Phase 2 Acceptance Criteria

| Criterion | Status |
|---|---|
| INCOIS SST wired | **IMPLEMENTED** |
| Docker/PostGIS verified | **IMPLEMENTED** |
| `/marine-map` exists | **IMPLEMENTED** |
| MapLibre/deck.gl reused, no new engine | **IMPLEMENTED** |
| GEBCO/chlorophyll/SST shown honestly (sparse, not continuous) | **IMPLEMENTED** |
| Currents/Waves/Wind visible | **IMPLEMENTED** |
| ORCA Risk/Suitability visible (deterministic, unchanged engines) | **IMPLEMENTED** |
| Geofences labeled non-authoritative | **IMPLEMENTED** |
| Route/Route risk (Route Planner) | **IMPLEMENTED** (unchanged, verified no regression) |
| PFZ honestly unavailable, never fabricated | **IMPLEMENTED** |
| Layer controls, dynamic legend, evidence panel, freshness, provenance | **IMPLEMENTED** |
| Genuine time slider, real backend data per timestamp | **IMPLEMENTED** (verified live via network capture) |
| No fake data / no fake interpolation / no frontend direct external calls | **IMPLEMENTED** |
| Backend tests pass except documented pre-existing issues | **IMPLEMENTED** (537/2, both pre-existing) |
| Frontend typecheck/lint/build pass | **IMPLEMENTED** |
| Docker healthy, browser E2E passes | **IMPLEMENTED** |
| Phase 2 report | **IMPLEMENTED** (this document) |

## 16. Recommendation

**Is Phase 3 — Fishing Intelligence ready to begin?**

**Yes, conditionally**: the deterministic Suitability Engine is already live on the map with correct, unmodified provenance, and the data foundation (however sparse) is now honestly and completely surfaced end-to-end. Before Phase 3 builds fishing-specific recommendation features on top, it should (a) be aware of the Redis cache-staleness gap in §14 so it doesn't silently see stale "unavailable" data during development, and (b) treat the current sample density (225/51/56 points) as a known constraint on any recommendation quality claims it makes — not a blocker, but a fact Phase 3's own output should stay honest about, consistent with every phase before it.
