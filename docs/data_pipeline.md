# Phase 1 — Data Foundation

This document describes what is actually implemented for Phase 1. See
[`docs/architecture.md`](architecture.md) for the frozen architecture this implements
against, and [`docs/demo_region.md`](demo_region.md) for the DEMO_BBOX proposal.

Phase 1 builds the data layer only — no agents, no LLM calls, no LangGraph, no risk
scoring, no routing. Its job is to hand later phases a reliable, normalized,
provenance-traceable environmental data layer.

```
EXTERNAL SOURCES (Open-Meteo Weather / Marine)
       |
       v
SOURCE ADAPTER  (fetch — HTTP, timeout, error handling)
       |
       v
RAW RESPONSE  (preserved verbatim under data/raw/)
       |
       v
VALIDATION + NORMALIZATION  (adapter.parse — units, CRS, timestamps, missingness)
       |
       v
MARINE DATA FABRIC  (app/fabric/fabric.py — applies the Temporal Validity Gate)
       |
       v
POSTGRESQL / POSTGIS  (app/data/storage.py — environmental_observations table)
```

## 1. Sources

| Source | Tier | Status |
|---|---|---|
| Open-Meteo Weather API | LIVE | Implemented — `app/data/open_meteo_weather.py` |
| Open-Meteo Marine API | LIVE | Implemented — `app/data/open_meteo_marine.py` |
| Natural Earth (coastline) | STATIC | Not yet acquired — see `docs/demo_region.md` |
| GEBCO (bathymetry) | STATIC | Not yet acquired — see `docs/demo_region.md` |
| WDPA (protected areas) | STATIC | Not yet acquired — needs DEMO_BBOX confirmation AND an API token |
| Marine Regions (EEZ) | STATIC | Not yet acquired — see `docs/demo_region.md` |

Neither Open-Meteo API requires an API key. No credentials are stored anywhere in this
phase.

## 2. Source adapters

`app/data/base.py` defines `SourceAdapter`, the common contract every adapter implements:
`fetch(latitude, longitude) -> RawResponse` (does the HTTP request, raises a typed
`SourceAdapterError` subclass on timeout/HTTP error/non-JSON response) and
`parse(raw, mode) -> list[NormalizedObservation]` (validates + normalizes). No business
logic anywhere else imports `httpx` or knows Open-Meteo's response shape — that isolation
is what lets a later Weather/Oceanographic Agent (Phase 4) call these adapters without
ever seeing a raw provider response.

`app/data/open_meteo_common.py` holds the parsing logic shared by both Open-Meteo
adapters (they return the same `hourly_units` + `hourly.time[]` envelope); each adapter
file only declares its own base URL and required parameters.

Phase 1 samples **one representative time step per fetch** — the hourly forecast bucket
that is current as of the retrieval time (`_select_current_step` in
`open_meteo_common.py`), not always the first element of the response array (which is
midnight UTC and may already be hours stale by the time ORCA calls it). This is a
deliberate, documented scope decision: a full time-series ingestion system is not
required to prove the pipeline end-to-end, and is left to a later phase if needed.

## 3. Raw data

Every successful fetch is preserved verbatim under `data/raw/<source>_<timestamp>.json`
(source, request URL, request params, retrieval time, full payload) before any
validation happens — see `app/data/base.py::_persist_raw`. This directory holds transient
API pulls only (`.gitignore`'d beyond a `.gitkeep`); it is never mixed with the curated
static/reference/demo datasets that will live under `data/static/`, `data/reference/`,
`data/demo/`.

## 4. Validation & normalization

Both happen inside each adapter's `parse()`, using shared helpers so logic isn't
duplicated:

- **Units** (`app/fabric/units.py`) — every `(parameter, source_unit)` pair is looked up
  explicitly; an unrecognized parameter or unit is rejected, never silently coerced.
  Canonical units: `m/s` (wind speed, current velocity), `degree` (all directions), `m`
  (wave height), `s` (wave period), `degC` (temperature), `mm` (precipitation),
  `wmo_code` (weather code, dimensionless). Source units are read from the API's own
  `hourly_units` field at request time, never assumed.
- **Coordinates** (`app/fabric/spatial.py`) — CRS is EPSG:4326 throughout; latitude/
  longitude are range-validated before a point can enter a `NormalizedObservation`.
- **Timestamps** — `observed_at` (when the value is valid for), `valid_from`/`valid_to`
  (the usability window — an hourly bucket, `[observed_at, observed_at + 1h)`), and
  `retrieved_at` (when ORCA fetched it) are kept explicitly distinct. All are UTC.
- **Missingness** — a missing/null field becomes an observation with `value=None` and
  `quality.is_missing=True` plus a reason, never a fabricated zero.

## 5. Data contracts

`app/models/contracts.py` defines two layers, matching two different parts of the
architecture:

- **`NormalizedObservation`** — the Fabric's internal schema (architecture.md §13's
  "common schema per observation"), extended with the quality/missingness/temporal-
  validity/live-vs-demo bookkeeping Phase 1 needs. This is what adapters produce and what
  gets stored in PostGIS.
- **`Evidence`** — the verbatim agent contract from architecture.md §12, used once real
  agents exist (Phase 4+). `NormalizedObservation.to_evidence(confidence=...)` converts
  one into the other; confidence itself is the Risk Engine's job (§22, Phase 2), not
  computed here.

Structural guarantees enforced by Pydantic validators (not just convention):
`value is None` if and only if `quality.is_missing` is `True`; `is_live` must always
equal `source_tier == "live"` — a demo/synthetic/cached/reference observation can never
claim to be live (architecture.md §16a).

## 6. Marine Data Fabric

`app/fabric/fabric.py::ingest()` is the boundary between adapters and every future
intelligence component. It takes already-normalized observations and applies the
Temporal Validity Gate uniformly, regardless of which adapter produced them, returning a
`FabricBatch`. No future agent is meant to see a raw provider response — only this.

## 7. Temporal validity

`app/fabric/temporal.py::evaluate_temporal_validity()` is a pure, deterministic function
— no LLM, no forecasting model — returning one of:

- `VALID` — usable now.
- `STALE` — still within its validity window, but retrieved too long ago relative to the
  requested time (default max staleness: 30 minutes for both weather and marine, per
  architecture.md §16's fallback table).
- `EXPIRED` — the requested time falls outside `[valid_from, valid_to]`.
- `INVALID_TIMESTAMP` — timestamps present but inconsistent (e.g. missing timezone, or
  `valid_from > valid_to`).
- `MISSING_TIMESTAMP` — no resolvable temporal anchor at all.

Verified against real data: `tests/test_pipeline_e2e.py::test_pipeline_through_temporal_validity`
fetches live Open-Meteo data and asserts it comes back `VALID`.

## 8. Static GIS

Directory structure exists (`data/static/`, `data/reference/`, `data/demo/`) and a
provenance registry table (`static_layer_sources`) is defined, but no static dataset has
actually been acquired yet — see `docs/demo_region.md` for why, and the honest
`not_acquired` rows that `scripts/ingest_demo_observations.py --register-static-sources`
seeds for Natural Earth, GEBCO, WDPA, and Marine Regions.

## 9. PostGIS storage

`app/data/storage.py` defines exactly two tables via SQLAlchemy Core + GeoAlchemy2
(parameterized throughout — no string-concatenated SQL):

- **`environmental_observations`** — one row per normalized observation, geometry column
  `geom GEOMETRY(POINT, 4326)` with a GiST index, plus a `(parameter, observed_at)` index.
  Carries the full quality/temporal-validity/mode bookkeeping from `NormalizedObservation`.
- **`static_layer_sources`** — the provenance registry from §8 above.

The final ORCA schema from architecture.md §33 (`queries`, `agent_runs`,
`recommendations`, `risk_cells`, `geofences`, `routes`, ...) is deliberately **not**
created here — those are later phases' business tables, not this phase's infrastructure.

## 10. Demo/live semantics

`ORCA_MODE` (session type: `live` or `demo`) and `source_tier` (where a specific piece of
evidence actually came from: `live`/`cached`/`static`/`reference`/`synthetic`) are kept as
the two independent concerns architecture.md §16a describes. A genuine successful
Open-Meteo call is always `source_tier="live"` and `is_live=True`, regardless of the
session's `ORCA_MODE` — a demo *session* does not retroactively make real data fake.
Conversely, `is_live` can never be `True` for anything tagged `static`/`reference`/
`synthetic`/`cached` — enforced structurally in `NormalizedObservation`'s validator, not
left to convention.

## 11. Testing

- `backend/tests/test_config.py`, `test_contracts.py`, `tests/fabric/*` — offline unit
  tests (config/bbox validation, contract invariants, unit conversion, spatial
  validation, temporal gate). Run with `pytest -m "not integration and not live"`.
- `backend/tests/data/*` — mocked Open-Meteo adapter tests (`respx`), covering valid
  responses, missing fields, null values, unknown units, malformed structure, invalid
  timestamps, HTTP errors, timeouts, and non-JSON responses. Same offline marker.
- `backend/tests/test_live_open_meteo.py` — real calls to both Open-Meteo APIs. Marked
  `@pytest.mark.live`; run explicitly with `pytest -m live`.
- `backend/tests/test_pipeline_e2e.py` — the full pipeline. The `live`-marked test goes
  through the Temporal Validity Gate with real data; the `integration`-marked test adds
  the PostGIS write and requires a reachable PostgreSQL/PostGIS instance (e.g. via
  `docker compose up`).
