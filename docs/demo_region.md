# Demo Region — DEMO_BBOX

**Status: PROPOSED — AWAITING CONFIRMATION.** This bounding box is not frozen anywhere in
`docs/architecture.md`. Architecture §44 fixes the region by *name*
("Mangaluru–Udupi coastal Karnataka") and explicitly leaves the exact numeric box open:
`DEMO_BBOX=<to be frozen>`. This document proposes the specific numbers so implementation
can proceed, but no large-scale static-data acquisition (Natural Earth, GEBCO, WDPA,
Marine Regions) has been run against it — that step is deliberately held back
until this proposal is confirmed, per the task instructions for Phase 1.

## Proposed values

```
DEMO_BBOX_MIN_LAT = 12.70
DEMO_BBOX_MIN_LON = 73.50
DEMO_BBOX_MAX_LAT = 13.45
DEMO_BBOX_MAX_LON = 75.05
```

These are the current defaults in `backend/app/config.py` and `.env.example`. Live
per-request calls (Open-Meteo) already use this box today — that is a reversible,
per-request API call, not a bulk/irreversible acquisition, so it is not gated on
confirmation the way static-dataset downloads are.

## What this region covers

- **North–south span** (12.70°N to 13.45°N, ≈83 km): from just south of Mangaluru city
  (Netravati/Gurupura river mouth, ~12.84°N) up past Udupi (~13.34°N) and Malpe port
  (~13.35°N), with a small buffer on both ends.
- **East–west span** (73.50°E to 75.05°E, ≈167 km at this latitude): from ~27 km inland
  of the coast (covering the coastline itself, river mouths, and enough hinterland for
  CRZ-buffer/coastline geometry context) out to ~145 km offshore into the Arabian Sea —
  enough to cover nearshore fishing grounds and a meaningful offshore area for
  weather/wave/risk-grid and routing scenarios, without pulling in a global-scale dataset.
- Mangaluru (12.87°N, 74.88°E) and Udupi (13.34°N, 74.75°E) both fall inside this box
  (enforced by `tests/test_config.py::test_default_demo_bbox_covers_mangaluru_and_udupi`).

## Suitability check

| Use | Assessment |
|---|---|
| Open-Meteo requests | Verified live against this box's center point (13.075°N, 74.275°E) — a valid offshore point; both Weather and Marine APIs return data (see `tests/test_live_open_meteo.py`). |
| Coastline (Natural Earth) | Box includes enough inland buffer to capture the coastline geometry, river mouths, and a usable buffer for illustrative CRZ polygons. |
| Bathymetry (GEBCO) | Offshore extent (~145 km) is enough to show a meaningful depth gradient from the coast into open water for future risk/routing use. |
| Protected areas (WDPA) | Box is large enough to plausibly contain any coastal/marine protected areas near Mangaluru–Udupi, if present in WDPA's data for this stretch. |
| EEZ (Marine Regions) | India's territorial sea/EEZ boundary lies far further offshore than this box's western edge; this box does not claim to reach the EEZ line itself — it only needs to be internally consistent for the demo's nearshore fishing/routing scenarios, not to depict the full EEZ. |
| Future risk grid | At a 2–5 km cell size (architecture.md §18), this box is roughly 17–40 cells N–S by 33–80 cells E–W — a demo-appropriate grid size, not global-scale. |
| Future routing | Enough offshore room for a multi-cell A* route from a coastal origin to an offshore candidate zone (architecture.md §26). |
| Frontend map | A ~83 km × 167 km box renders at a sensible default zoom level for a coastal demo map, not a tiny point or a whole-country view. |

## What is explicitly NOT done yet

Per the Phase 1 task scope, this proposal does **not** trigger:
- Downloading Natural Earth coastline data
- Downloading/clipping GEBCO bathymetry
- Requesting/using a WDPA API token or downloading WDPA polygons
- Downloading Marine Regions EEZ data

`static_layer_sources` rows for all four datasets are seeded with
`acquisition_status = "not_acquired"` (see `scripts/ingest_demo_observations.py
--register-static-sources`), each recording exactly why: pending this confirmation, and
— for WDPA specifically — also pending an API token (architecture.md §14: "Free token via
request form").

## Next step

Once this bbox is confirmed (or amended), the same box must be used consistently
throughout the project — update `demo_bbox_min_lat` / `demo_bbox_min_lon` /
`demo_bbox_max_lat` / `demo_bbox_max_lon` in `backend/app/config.py` and `.env.example`
together, then proceed with the static-dataset acquisition steps this document currently
defers.
