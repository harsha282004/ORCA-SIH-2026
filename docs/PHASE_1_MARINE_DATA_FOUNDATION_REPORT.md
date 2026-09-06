# Phase 1 — Marine Data Foundation Report

## 1. Executive Summary

Phase 1 acquired and integrated **real** data for three of the four target datasets, and genuinely upgraded Open-Meteo from a single representative value to a real multi-timestep series. All acquisition happened via live, verified, unauthenticated public services — no credentials, no fabricated values, no invented URLs.

- **GEBCO bathymetry**: **IMPLEMENTED**. 225/225 real depth samples acquired from GEBCO's own live WMS (`GEBCO_2026 Grid`), now served by `GET /api/v1/layers/bathymetry`.
- **INCOIS chlorophyll**: **IMPLEMENTED**. 51/64 real samples acquired from INCOIS's own live WMS, now served by a new `GET /api/v1/layers/chlorophyll`.
- **INCOIS SST** (bonus — not originally required, discovered during PFZ investigation): 56/64 real samples from the same INCOIS service, recorded with full provenance (not yet wired to a dedicated endpoint — Open-Meteo remains the primary SST source per the existing architecture).
- **Official INCOIS PFZ (vector)**: **UNAVAILABLE — investigated in depth, confirmed not machine-readable**. No fabricated PFZ polygon was created. Full investigation trail in §6.
- **Multi-timestep marine data**: **IMPLEMENTED**. New `GET /api/v1/layers/marine-timeseries` returns a genuine 24-point real hourly series (verified: 3+ distinct real timestamps in tests, 24 in production) from the same Open-Meteo adapters already in use, via one new additive parsing function.

Total real data acquired this phase: **358,180 bytes (349.8 KiB)** across raw + processed artifacts, measured directly from disk (see §4).

## 2. Repository Baseline

Before this phase: `static_layer_sources` (PostGIS) existed but was empty — GEBCO/PFZ/chlorophyll were all explicitly `not_acquired` (see `app/agents/gis/agent.py`'s own module docstring). `/api/v1/layers/bathymetry` always returned `UNAVAILABLE`; there was no chlorophyll layer endpoint at all; Open-Meteo agents resolved exactly one representative hourly value per call (`app/data/open_meteo_common.py::parse_hourly_observations`). The Marine Intelligence Map (built in the prior phase) already had real risk-surface, geofences, suitability, SST/wave/current (Open-Meteo), route, and route-risk layers — none of that was touched or duplicated.

## 3. Dataset Acquisition Summary

| Dataset | Provider | Status | Source | Downloaded? |
|---|---|---|---|---|
| GEBCO bathymetry | GEBCO Compilation Group (IHO/IOC UNESCO) | **Acquired** | `https://wms.gebco.net/mapserv` (live WMS) | Yes — 225 real point samples + 1 reference image |
| INCOIS Chlorophyll | ESSO-INCOIS | **Acquired** | `https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms` | Yes — 64 requested, 51 real values + 1 reference image |
| INCOIS SST | ESSO-INCOIS | **Acquired** (supplementary) | same as above | Yes — 64 requested, 56 real values + 1 reference image |
| Official INCOIS PFZ (vector) | ESSO-INCOIS | **Unavailable** | investigated, no vector service found | No — nothing to download |
| Open-Meteo multi-timestep | Open-Meteo | **Implemented** (live, per-request) | existing adapters, new series parser | N/A — live API, not a static download |

## 4. EXACT DATASET SIZE REPORT

All sizes measured directly from disk (`wc -c` / filesystem stat) on 2026-09-06, immediately after acquisition. SHA-256 checksums computed the same way.

| Dataset | Raw Size | Reference Image | Processed Size | Files | Samples/Features |
|---|---:|---:|---:|---:|---:|
| GEBCO bathymetry | 40,879 bytes | 56,986 bytes (PNG) | 57,767 bytes | 3 | 225 requested / 225 with a value |
| INCOIS Chlorophyll | 12,127 bytes | 110,091 bytes (PNG) | 15,871 bytes | 3 | 64 requested / 51 with a value |
| INCOIS SST | 12,009 bytes | 32,514 bytes (PNG) | 17,167 bytes | 3 | 64 requested / 56 with a value |
| Manifest (`phase1_data_manifest.json`) | — | — | 2,769 bytes | 1 | — |
| **Total** | **264,606 bytes raw+images** | | **93,574 bytes processed (incl. manifest)** | **10** | **353 requested / 332 with a value** |

**Grand total new on-disk footprint: 358,180 bytes (349.80 KiB).**

For rasters (GEBCO is point-sampled, not a raster file, so "grid" = sample grid, not pixel dimensions):
- GEBCO: 15×15 = 225 sample points; each carries `depth_m` + `tid` (GEBCO's own Type Identifier code).
- Reference images are real WMS `GetMap` PNGs, not rasterized from the samples: GEBCO 1024×1024 (56,986 bytes), INCOIS chl 1024×1024 (110,091 bytes), INCOIS sst 1024×1024 (32,514 bytes).

For vectors (all three processed artifacts are GeoJSON Point FeatureCollections):
- GEBCO: 225 Point features, geometry type `Point`.
- INCOIS chl: 51 Point features (13 requested points returned no value — land/edge gaps, honestly excluded).
- INCOIS sst: 56 Point features (8 requested points were a `-1.0` land/masked-pixel sentinel, detected and excluded — see §15).

For the time series:
- `GET /api/v1/layers/marine-timeseries` returns 24 real timestamps per request (Open-Meteo's `forecast_days=1` hourly cadence), 11 variables per timestamp (5 weather + 6 marine) — verified live (not estimated) via `curl` during this task.

Checksums (SHA-256, full values in `data/processed/phase1_data_manifest.json`):
- GEBCO raw: `e038280de79a97a80f02d39887689b05ee5fdca3a60d80ec27b598330051d18d`
- GEBCO processed: `73c60f710aa99b2f827c4f5dbd431383cffe5155c23dbfec82a08456aaf5e717`
- INCOIS chl raw: `3564a27e2350981e7d8a150d80e1141826f41dad61c861892f253ae8d3e3b2f3`
- INCOIS chl processed: `3ff6557349958214008945428cdbbbc1e3a279369d4f168edb44849673269d4d`
- INCOIS sst raw: `de18270a1feffa2819894a2d617a1885f0ec4a08c7ff772fa535d19b079a2c6a`
- INCOIS sst processed: `edd687b07f9dcda186398d0d6de0b280194421f3a1cd9b7610a8c6c86a221513`

## 5. GEBCO

- **Dataset/product**: GEBCO_2026 Grid (confirmed live from the WMS's own `GetCapabilities` `<Abstract>`: "It currently provides access to the GEBCO_2026 Grid... a global elevation model at 15 arc-second intervals").
- **Version**: GEBCO_2026 Grid (the current release at acquisition time).
- **Source**: `https://wms.gebco.net/mapserv` (GEBCO's own official live WMS; `https://www.gebco.net/data-products/gridded-bathymetry-data` is the reference/documentation page).
- **Access method**: OGC WMS 1.1.1 `GetFeatureInfo` on layer `GEBCO_LATEST_2` (elevation) and `GEBCO_LATEST_TID_2` (Type Identifier). GEBCO's bulk "Grid Subsetting App" (`download.gebco.net`) was investigated first and found to be a Next.js SPA with no discoverable stable scripted API; GEBCO's own WCS was tested and found broken on the public server (empty `ContentMetadata`, "problem with one of layers" warnings). The WMS was the genuinely working, scriptable, official path.
- **Resolution**: acquired as a 15×15 = 225-point bounded regional sampling grid (see `app/data/gebco.py`'s module docstring) — NOT the native 15 arc-second grid (~67,000 points for this bbox), a deliberate, documented, bounded extraction consistent with the existing architecture's own sampling philosophy (`app.agents.environmental_provider`).
- **BBox**: exactly the existing `DEMO_BBOX` (12.70–13.45°N, 73.50–75.05°E) — unchanged, never invented.
- **CRS**: EPSG:4326.
- **Depth convention**: negative = below sea level, positive = land elevation, meters (GEBCO's own convention, verified against real returned values, e.g. -1795m to 153m across this bbox — the positive value is a real land sample near the coast, not an error).
- **File sizes**: see §4.
- **Validation**: bbox overlap confirmed (all 225 sample coordinates fall inside the requested bbox by construction); depth range (-1795 to 153m) is physically plausible for this stretch of the Arabian Sea continental shelf/slope; 225/225 samples returned a real value (0 gaps).
- **Storage**: `data/raw/gebco/` (raw WMS responses + one reference PNG), `data/processed/gebco_bathymetry_orca_bbox.geojson` (application-ready), `static_layer_sources` (PostGIS provenance row).
- **API**: `GET /api/v1/layers/bathymetry` — serves the real GeoJSON when acquired, an honest `UNAVAILABLE` response otherwise (never fabricated).
- **Map integration**: new `buildBathymetryLayer` (deck.gl `ScatterplotLayer`, blue depth gradient), wired into the existing Route Planner's layer control/legend/evidence panel — no redesign.

## 6. INCOIS PFZ

**Investigated in depth. No official machine-readable vector PFZ service was found. Nothing was fabricated.**

Official sources investigated:
- `https://incois.gov.in/MarineFisheries/PfzWebGis`
- `https://incois.gov.in/geoportal/MFASPFZ/index.html`
- `https://incois.gov.in/gisserver/PFZ/index.html` — **404 Not Found** (confirmed dead).
- `https://incois.gov.in/MarineFisheries/PfzAdvisory`

Access methods tested:
- The `MFASPFZ` geoportal is backed by a real, live, public **GeoServer** instance at `https://incois.gov.in/geoserver/`.
- **WFS** `GetCapabilities` (`.../PFZ-TUNA-SST-CHL/ows?service=WFS&version=2.0.0&request=GetCapabilities`) returns a **valid but completely empty `FeatureTypeList`** — verified by fetching and parsing the raw 92,625-byte XML response directly (not summarized). There is no vector PFZ (or any other) feature type registered on this GeoServer instance.
- **WMS** `GetCapabilities` on the same workspace lists real layers: `chl` ("Chlorophyll Concentration"), `sst` ("Sea Surface Temperature"), and a styling asset named `pfz_tuna_chl_sld` — but no distinct PFZ polygon/point coverage. (It also lists GeoServer's own stock demo layers — `spearfish`, `tasmania`, `tiger-ny` — confirming this is a lightly-customized default GeoServer install, not a purpose-built PFZ feature service.)

**Conclusion**: PFZ is genuinely published by INCOIS only as a rendered advisory product (maps/bulletins via `PfzAdvisory`/`PfzWebGis`), not as downloadable/queryable vector geometry through any public endpoint discovered. This matches PFZ's real-world nature — it is `INCOIS`'s advisory synthesis of chlorophyll + SST fronts, not itself a separately-stored geometry layer on this server.

**What remains available and IS integrated instead**: the two real satellite-derived inputs INCOIS's own PFZ methodology is built from — chlorophyll and SST — both acquired and served (§5 is bathymetry; chlorophyll is §7; INCOIS SST is recorded in the manifest/DB but not yet given its own dedicated endpoint, since Open-Meteo remains the primary SST source per the pre-existing architecture).

**What remains to be done**: if INCOIS ever publishes an official PFZ vector/WFS layer, or grants access to an internal one, integrating it only requires adding one more `app/data/*.py` client and one more `GET /api/v1/layers/pfz` endpoint following the exact same pattern already established for bathymetry/chlorophyll — no architectural change needed. The map's `INCOIS PFZ Reference` toggle is deliberately shown **disabled** (not hidden, not faked) in the layer control, honestly signaling "not available in this deployment."

## 7. CHLOROPHYLL

- **Provider**: ESSO-INCOIS (the same organization responsible for the official PFZ product — chosen over a generic global NOAA/NASA ERDDAP source specifically because it is INCOIS's own India-region operational input, directly relevant to PFZ, and was found live during the PFZ investigation itself).
- **Dataset**: "Chlorophyll Concentration" WMS coverage, workspace `PFZ-TUNA-SST-CHL`.
- **Variable / units**: chlorophyll-a concentration, **mg/m³ (inferred)** — INCOIS's GeoServer publishes no machine-readable units field on this coverage; mg/m³ is inferred from the observed value range (0.14–7.38, matching known coastal-India chlorophyll-a ranges) and from INCOIS's own published PFZ methodology description. Documented as an inference, not confirmed via service metadata (see `app/data/incois_wms.py`'s module docstring).
- **Resolution**: acquired as an 8×8 = 64-point bounded regional sampling grid.
- **Temporal resolution/coverage**: INCOIS's WMS advertises no time dimension — this is their current operational snapshot only, never a historical archive. Represented honestly as such (`temporal_semantics` field in the API response).
- **Source URL**: `https://incois.gov.in/geoportal/MFASPFZ/index.html` (portal); `https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms` (the actual service).
- **Download/processed size**: see §4.
- **Integration status**: **Implemented**. `GET /api/v1/layers/chlorophyll` serves the real data; `buildChlorophyllLayer` renders it (deck.gl `ScatterplotLayer`, green concentration gradient) with an explicit "not fish abundance" disclaimer in the evidence panel.
- **Data quality note**: 13/64 requested points returned no value (land/coastal-edge gaps in the coverage) — honestly excluded, not interpolated or fabricated.

## 8. TEMPORAL MARINE DATA

- **Variables**: `temperature_2m`, `wind_speed_10m`, `wind_direction_10m`, `weathercode`, `precipitation` (weather) + `wave_height`, `wave_direction`, `wave_period`, `sea_surface_temperature`, `ocean_current_velocity`, `ocean_current_direction` (marine) — the exact same 11 parameters the existing agents already fetch, no new variables invented.
- **Number of timestamps**: 24 real hourly steps per request (Open-Meteo's `forecast_days=1` cadence) — verified live.
- **Temporal resolution**: 1 hour (Open-Meteo's native cadence, unchanged).
- **Temporal coverage**: the current UTC day, forecast-sourced (never claimed as "observation").
- **Number of records**: 24 timestamps × 11 variables = 264 real values per single-point request.
- **Data source**: the exact same `OpenMeteoWeatherAdapter`/`OpenMeteoMarineAdapter` already in production — reused unchanged; only a new, additive `parse_hourly_timeseries` function reads the SAME already-fetched raw payload a second, fuller way.
- **API**: new `GET /api/v1/layers/marine-timeseries?latitude=&longitude=` (rejects points outside `DEMO_BBOX` with `OUT_OF_DOMAIN`).
- **Caching**: unchanged — this endpoint calls the adapters directly (not through the cached agents), by design, so a genuine fresh series is always returned; this is an acceptable cost for a point-detail/time-slider-data endpoint, not a per-cell bulk operation.
- **Freshness semantics**: `is_forecast: true` on every record — never mislabeled as an observation.

## 9. Data Model

- **`static_layer_sources`** (PostGIS, pre-existing table): added one new column, `metadata JSONB` (nullable), applied via a new idempotent `_ensure_schema_upgrades()` helper (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — no Alembic/migration framework introduced, matching the "frozen architecture" constraint. Used to store exact acquisition metadata (sample counts, value ranges) without a column-per-fact schema.
- **No new tables.** `environmental_observations` was considered for the point samples but the simpler, purpose-fit choice (matching the pattern the Route Planner map already uses for risk-surface/suitability/oceanography) was flat GeoJSON files under `data/processed/`, read directly by the API — consistent with `static_layer_sources.acquisition_status` already distinguishing `not_acquired`/`acquired`/`processed`/`loaded`.
- **`app/agents/gis/agent.py`**: `_query_dataset_status` now passes through `source_name`/`source_url`/`dataset_version`/`acquired_at`/`geographic_coverage`/`metadata` from the DB row (previously only 3 fields); added `get_chlorophyll_status()` alongside the existing `get_bathymetry_status()`.

## 10. Data Provenance

Every acquired dataset has a `static_layer_sources` row recording provider, source URL, dataset version, acquisition timestamp, geographic coverage, and a `metadata` JSONB blob (sample counts, value ranges, checksums via the manifest). The API surfaces this directly: `GET /api/v1/layers/bathymetry` and `/chlorophyll` both include `source`, `source_url`, `dataset_version`/`is_authoritative`, and `acquired_at` in their `meta` object, so the frontend evidence panel can (and does) show exactly where a value came from.

## 11. Freshness

Reused the existing `classify_freshness_status()` (introduced in the prior Marine Intelligence Map phase) — no second freshness system. Bathymetry is `STATIC` (GEBCO's grid changes on a multi-year release cycle, never given a fake hourly timestamp). Chlorophyll is `CURRENT` (INCOIS's own live operational snapshot — no historical archive exists to compare staleness against, so "current as of this acquisition" is the honest, available signal). The new time-series endpoint marks every record `is_forecast: true`, never "observation."

## 12. API Changes

New endpoints (all under the existing `/api/v1/layers/*` convention — no parallel API design):
- `GET /api/v1/layers/chlorophyll` — real INCOIS chlorophyll.
- `GET /api/v1/layers/marine-timeseries?latitude=&longitude=` — real multi-timestep Open-Meteo series.

Modified endpoints:
- `GET /api/v1/layers/bathymetry` — now serves real GEBCO data when acquired (previously always `UNAVAILABLE`); falls back to the same honest unavailable response if not.
- `GET /api/v1/layers/oceanography` — `chlorophyll.reason` now points to the new dedicated endpoint instead of a blanket "not integrated" message.

No existing endpoint's request/response contract was broken; `/api/v1/route` and `/api/v1/query` were not touched.

## 13. Map Integration

| Layer | Before Phase 1 | After Phase 1 |
|---|---|---|
| Bathymetry | UNAVAILABLE (toggle showed an honest banner) | **AVAILABLE** — real GEBCO depth points |
| Chlorophyll | UNAVAILABLE (no endpoint existed) | **AVAILABLE** — real INCOIS chlorophyll points |
| INCOIS PFZ | UNAVAILABLE (disabled toggle) | Still UNAVAILABLE — now backed by a much deeper, documented investigation (§6), toggle remains honestly disabled |
| SST/Waves/Currents | Real (Open-Meteo, single value) | Unchanged; a real 24-point series is now available via the new timeseries endpoint for any point, not yet wired into a UI time slider (see §17) |

## 14. Validation

**Backend**: `pytest -q` → **536 passed, 2 failed**. Both failures are environment-dependent, not regressions:
1. `tests/api/test_query_llm_not_configured.py` — pre-existing (documented in the prior Groq-verification task): this repo's Groq configuration makes the "no LLM provider configured" premise false in this environment.
2. `tests/agents/gis/test_agent.py::test_static_dataset_status_unreachable_db_reports_unknown_not_available` — **newly surfaced by this task's own success**: the test's docstring explicitly assumes "we don't have a live PostGIS instance in this test environment," which was true before Phase 1 but is no longer true now that GEBCO has been genuinely, successfully acquired into the real, running, shared PostGIS instance this test suite happens to run against. Not modified, per instruction.

New tests added this phase: `tests/data/test_gebco.py` (4 structural + 1 live), `tests/data/test_incois_wms.py` (3 structural + 1 live), plus 6 new/updated tests in `tests/api/test_layers.py` (bathymetry acquired/unacquired, chlorophyll acquired/unacquired, marine-timeseries domain-check + genuine-series-check).

**Frontend**: `tsc -b` → PASS (0 errors). `eslint .` → PASS (0 errors, 0 warnings). `npm run build` → PASS (one non-blocking chunk-size advisory, pre-existing from deck.gl).

**Docker**: `docker compose build backend && build frontend` → both succeed. `docker compose ps` → all 4 services healthy. `GET /health` → 200. `GET /api/v1/health/ready` → all dependencies healthy.

**E2E (live browser)**: Route Planner loads; Bathymetry and Chlorophyll toggles both fetch real data and render (screenshot-verified: distinct blue-gradient depth points and green-gradient chlorophyll points, correctly overlaid with the existing risk surface, geofence, and route layers); zero console/page errors; exactly the expected `GET /api/v1/layers/*` calls fired, no direct external-provider calls from the browser.

## 15. Data Quality Findings

- **GEBCO**: 0 gaps (225/225). One sample landed on land (positive elevation, +153m) — correctly rendered, not filtered, since land elevation is a real, valid GEBCO value, not an error.
- **INCOIS chlorophyll**: 13/64 points returned no value — coastal/edge gaps in the coverage, honestly excluded.
- **INCOIS SST**: found and fixed a real data-quality issue live during this task — INCOIS's SST layer returns `-1.0` for land/masked pixels (not a physically real Arabian Sea temperature). This is a **documented inference** (INCOIS publishes no formal NODATA code for this coverage), applied as a plausibility-range filter (`0–45°C`) in `app/data/incois_wms.py`. 8/64 points were correctly excluded as a result.
- **Redis cache staleness (found and fixed live)**: `GISGeofencingAgent`'s 24-hour dataset-status cache initially kept serving `not_acquired` for several minutes after a real, successful acquisition, because nothing invalidated it. Fixed by having the acquisition script explicitly delete the relevant cache keys after a successful run (`app/services/cache`, no new caching framework).
- **GEBCO WMS quirk (found and fixed live)**: querying a unique tiny bbox per sample point made GEBCO's public MapServer instance return "no results" for most fresh points; switching to one fixed bbox/pixel-grid frame with only the pixel index varying per sample fixed this to 100% success — documented in `app/data/gebco.py`.

## 16. Storage Footprint

- Raw data total (this phase): 264,606 bytes (258.4 KiB).
- Processed data total (this phase, incl. manifest): 93,574 bytes (91.4 KiB).
- Database footprint: 3 new rows in `static_layer_sources` (each well under 2 KiB including the JSONB metadata blob) — negligible, not separately measured at the page level.
- **Total additional storage this phase: 358,180 bytes (349.80 KiB)**, measured directly from disk.

## 17. Remaining Limitations

- **Official INCOIS PFZ vector data does not exist as a public machine-readable service** — confirmed, not merely assumed (§6). Only a future INCOIS-side change (or private API access) can close this gap.
- **INCOIS chlorophyll/SST have no historical time dimension** in their WMS — only a current snapshot is obtainable; a true PFZ-relevant time series for these two variables is not possible from this source today.
- **No frontend time slider yet** — the new `marine-timeseries` endpoint makes one genuinely possible, but wiring an actual UI scrubber was out of this phase's scope (explicitly a data-foundation phase, not a UI phase) and would need per-point (not per-grid-cell) interaction design.
- **GEBCO/INCOIS sampling is a bounded regional grid, not the native full-resolution grid** — a deliberate, documented choice (§5/§7), not a limitation of access, but real full-resolution bathymetry (~67,000 points for this bbox) was not acquired.
- **`test_static_dataset_status_unreachable_db_reports_unknown_not_available`** now fails in any environment where the acquisition script has actually been run against the shared DB (§14) — a test-environment assumption that predates this phase's own success, left unmodified per instruction.

## 18. Files Changed

**New:**
- `backend/app/data/gebco.py`, `backend/app/data/incois_wms.py`
- `backend/scripts/acquire_marine_data_foundation.py`
- `backend/tests/data/test_gebco.py`, `backend/tests/data/test_incois_wms.py`
- `frontend/src/components/map/mapLayers.ts` — `buildBathymetryLayer`, `buildChlorophyllLayer` added
- `data/raw/gebco/*`, `data/raw/incois/*`, `data/processed/gebco_bathymetry_orca_bbox.geojson`, `data/processed/incois_chl_orca_bbox.geojson`, `data/processed/incois_sst_orca_bbox.geojson`, `data/processed/phase1_data_manifest.json`
- `docs/PHASE_1_MARINE_DATA_FOUNDATION_REPORT.md` (this file)

**Modified:**
- `backend/app/api/v1/layers.py` — bathymetry now serves real data; new chlorophyll + marine-timeseries endpoints.
- `backend/app/agents/gis/agent.py` — richer `_query_dataset_status`, new `get_chlorophyll_status()`.
- `backend/app/data/storage.py` — new `metadata` JSONB column + idempotent schema-upgrade helper.
- `backend/app/data/open_meteo_common.py` — new additive `parse_hourly_timeseries` function (existing `parse_hourly_observations` untouched).
- `docker-compose.yml` — added `./data:/app/data` volume mount (previously the container could not see the repo's own `data/` directory at all).
- `frontend/src/lib/api.ts` — `ChlorophyllLayerMeta`, richer `BathymetryLayerMeta`, `getChlorophyllLayer()`.
- `frontend/src/components/map/EvidencePanel.tsx`, `MapLegend.tsx` — bathymetry/chlorophyll evidence fields and legend entries.
- `frontend/src/routes/RoutePlannerPage.tsx` — bathymetry/chlorophyll wired into layer control, status panel, and unavailable-banner logic.

## 19. How to Reproduce

```bash
# From the repo root, with the stack running (docker compose up -d):
docker compose exec backend python scripts/acquire_marine_data_foundation.py

# Or locally (from backend/, with the same Python env the app uses):
cd backend && python scripts/acquire_marine_data_foundation.py

# Verify:
curl http://localhost:8000/api/v1/layers/bathymetry
curl http://localhost:8000/api/v1/layers/chlorophyll
curl "http://localhost:8000/api/v1/layers/marine-timeseries?latitude=12.8&longitude=74.2"

# Tests:
cd backend && pytest tests/data/test_gebco.py tests/data/test_incois_wms.py tests/api/test_layers.py -v
pytest -q   # full regression suite
```

## 20. Final Phase Status

| Target | Status |
|---|---|
| GEBCO bathymetry acquired + integrated | **IMPLEMENTED** |
| Official INCOIS PFZ (vector) | **UNAVAILABLE** (deeply investigated, documented, no fabrication) |
| Authoritative chlorophyll acquired + integrated | **IMPLEMENTED** (INCOIS) |
| INCOIS SST (bonus, supplementary to Open-Meteo) | **IMPLEMENTED** (recorded, not yet a dedicated endpoint) |
| Multi-timestep marine data + time-series API | **IMPLEMENTED** |
| Dataset manifest with exact sizes | **IMPLEMENTED** (`data/processed/phase1_data_manifest.json`) |
| Provenance / freshness preserved | **IMPLEMENTED** (existing frameworks reused, not duplicated) |
| Frontend time slider | **PARTIAL** — backend contract exists, UI not built (out of this phase's scope) |
