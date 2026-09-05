# Phase 2 — Deterministic Core

This document describes what is actually implemented for Phase 2. See
[`docs/architecture.md`](architecture.md) for the frozen architecture this implements
against, and [`docs/data_pipeline.md`](data_pipeline.md) for Phase 1's data foundation
this builds on.

Phase 2 implements ORCA's deterministic reasoning and safety layer: GIS operations, the
Risk Engine, confidence, the Fishing Suitability Engine, the Policy & Safety Guard, and
the Decision Engine. **Nothing in this phase calls an LLM, and nothing in it ever will** —
that boundary is structural, not a convention (see §11 below).

```
NORMALIZED OBSERVATIONS (Phase 1 contract)
       |
       v
GIS VALIDATION  (app/gis/geometry.py, app/fabric/spatial.py)
       |
       v
GEOFENCE CHECK  (app/gis/geofence.py — hard blocks only)
       |
       v
RISK COMPONENTS (app/risk/components.py, app/risk/hazard_proxies.py)
       |
       v
RISK SCORE / LEVEL (app/risk/engine.py)
       |
       v
CONFIDENCE (app/reasoning/confidence.py — computed separately, never folded into risk_score)
       |
       v
SAFETY GUARD (app/policy/safety_guard.py)
       |
       v
DECISION ENGINE (app/decision/engine.py)
       |
       v
STRUCTURED DECISION
```

Verified end-to-end with fixture data in `backend/tests/test_phase2_e2e.py`.

## 1. Module layout and one documented interpretation decision

Architecture.md §42's repository tree attributes "confidence" to `reasoning/` in a code
comment (`# temporal_gate, fusion, arbitration, conflicts, confidence (§17-20)`), but the
actual confidence *formula* is defined in §22 (the Risk Engine section), and §22's own
prose says the confidence weights are "stored in the same versioned config as the risk
weights (`backend/app/risk/risk_weights.yaml`)". Both signals are honored rather than
picking one and ignoring the other: the confidence **code** lives in
`app/reasoning/confidence.py` (matching the repo-tree module assignment), while the
confidence **weights** live in `app/risk/risk_weights.yaml` alongside the risk weights
(matching the explicit narrative instruction). `app/reasoning/confidence.py` imports its
weight type from `app.risk.config`.

Spatial-temporal fusion, evidence arbitration, and conflict resolution (architecture.md
§18-20) are **not** implemented — they require reconciling multiple agents' evidence for
the same factor, which doesn't exist until real data agents exist (Phase 4+).

## 2. GIS (`app/gis/`)

- **`geometry.py`** — polygon validity per Shapely/OGC rules (no self-intersections,
  non-empty). Point validation reuses Phase 1's `app.fabric.spatial.validate_point`
  rather than duplicating it. Invalid geometry raises `InvalidGeometryError` unless the
  caller explicitly passes `repair=True`, in which case `shapely.make_valid` is used and
  the result always reports `was_repaired=True` — never a silent fix.
- **`distance.py`** — `haversine_km` (verified against the ~344km London-Paris
  reference distance) for point-to-point, and `distance_to_polygon_km` (a local
  equirectangular projection + planar distance — an engineering approximation accurate to
  roughly 1% at the ORCA demo bbox's scale, explicitly **not** navigation-grade).
- **`geofence.py`** — see §3 below.
- **`grid.py`** — deterministic candidate-cell rasterization of a bbox (architecture.md
  §18's "grid of candidate cells"). See §6.

## 3. Geofencing — hard vs. soft (architecture.md §25)

**Hard** (blocks outright): `land`, `protected_area`, `international_boundary`,
`restricted_zone` (e.g. an active time-bound fishing-ban zone). A point inside — or
exactly on the boundary of — an active hard geofence is blocked;
`evaluate_point_against_geofences` returns a structured `GeofenceCheckResult`
(`allowed`, `blocked`, `constraint_type`, `reason`, `matched_geofence_id`, `distance_km`,
`source`, `is_authoritative`), not a bare boolean.

**Soft** (increases risk, never blocks): high waves, strong wind, strong currents, long
distance from coast. These are continuous risk factors, not polygon membership checks —
they are handled entirely inside the Risk Engine (`wave_risk`, `wind_risk`,
`coast_distance_risk`), which happens to consume `nearest_hard_geofence_distance_km` from
this module for the `restricted_zone_distance` factor.

`is_authoritative` and time-bound `active_from`/`active_to` windows are carried exactly
per architecture.md §25 — a synthetic/demo polygon is never indistinguishable from a real
one in this data model. **No real geofence data has been acquired** (Phase 1 did not
download WDPA/EEZ/coastline data — see `docs/demo_region.md`); every `Geofence` in the
Phase 2 test suite is a fixture, clearly labeled `source="fixture"`.

## 4. Risk Engine (architecture.md §22)

**Weights** (`backend/app/risk/risk_weights.yaml`, loaded and validated by
`app/risk/config.py`) — exactly as frozen by the architecture:

| Factor | Weight |
|---|---|
| wave | 0.25 |
| wind | 0.15 |
| advisory_or_hazard_flag | 0.20 |
| lightning_thunderstorm_proxy | 0.10 |
| restricted_zone_distance | 0.15 |
| coast_distance | 0.10 |
| data_confidence_penalty | 0.05 |

**A weight set that does not sum to 1.0 fails fast** at model-construction time
(`WeightSumError`, surfaced as a Pydantic `ValidationError`) — never silently
renormalized. Verified in `backend/tests/risk/test_config.py`.

**Thresholds**: `LOW` if `score < 0.33`; `MODERATE` if `0.33 <= score < 0.66`; `HIGH`
otherwise — also loaded from the same YAML, not a magic number in `engine.py`.

**Formula**: `risk_score = Σ(normalized_component[i] × weight[i])`, clamped to `[0, 1]`
only to absorb floating-point drift (mathematically already bounded since every component
is in `[0, 1]` and weights sum to 1.0). Verified byte-for-byte against architecture.md
§22's own worked example in `backend/tests/risk/test_engine.py::test_architecture_worked_example_exact`:
inputs `(0.55, 0.40, 0.0, 0.0, 0.30, 0.10, 0.0)` → score `0.2525` → `LOW`.

**Per-factor raw-to-normalized curves** (`app/risk/components.py`) are Phase 2's own
documented engineering choice — the architecture specifies the weight names and gives one
illustrative worked example, but does not specify a normalization formula for e.g. "1.4m
wave height → 0.55". Simple linear-clamp curves with named, configurable saturation
points are used instead (e.g. wave risk saturates at 3.0m, wind at 20 m/s in Phase 1's
canonical units). **These curves, like the weights themselves, are ORCA's own
configurable project methodology — not a scientific or regulatory standard.**

**Missing data is never silently zero**: `NormalizedRiskComponents` fields default to
`None`, and `compute_risk` raises `MissingRiskComponentError` (naming exactly which
factors are missing) rather than treating an absent factor as risk-free.

## 5. Confidence (architecture.md §22)

`confidence = 0.40 × freshness + 0.35 × completeness + 0.25 × agreement`
(`app/reasoning/confidence.py`), weights loaded from the same `risk_weights.yaml`.
**Confidence is not risk** — it is never combined into `risk_score` except via the
explicit, separately-weighted `data_confidence_penalty` factor (0.05), which is a visible
design choice, not an accidental double-count. All three inputs are mandatory
(`ConfidenceInputs` has no defaults) — an unresolved freshness/completeness/agreement
score must be resolved by the caller, never silently treated as 0 or 1.

## 6. Deterministic spatial risk representation (architecture.md §18)

`app/gis/grid.py::generate_grid(bbox, resolution_km)` rasterizes a bbox into a
deterministic grid of `GridCell`s (same cell IDs and geometry every time for the same
inputs). **Phase 2 development default: 3 km** (`RiskGridResolution` — within
architecture's stated 2-5km MVP range) — an engineering configuration choice, not a
claimed scientific optimum. `app/risk/risk_cell.py::evaluate_cell` attaches an
already-computed `RiskResult` + confidence + `valid_time` + `data_quality` +
`constraints` to a cell, producing a `RiskCellResult`.

This is **not** the final `risk_cells` database table from architecture.md §33 (which
requires a `recommendation_id` that doesn't exist until a real query pipeline exists,
Phase 4+) — it is an in-memory representation, populated only from test fixtures in
Phase 2 (`backend/tests/risk/test_risk_cell.py`, `test_phase2_e2e.py`). No new PostGIS
table was added in Phase 2 — deliberately: building real spatial-temporal fusion storage
ahead of having real fused evidence to put in it was explicitly out of scope.

## 7. Fishing Suitability Engine (architecture.md §21)

`Zone Score = signal + safety (inverse risk) + distance + data_confidence`, weighted per
`app/suitability/suitability_weights.yaml` (also fail-fast validated to sum to 1.0).
Always labeled `"ORCA Fishing Suitability"` — **never presented as, or merged into, the
official PFZ.** `PFZReference` (`status: "unavailable" | "available"`) is carried purely
as an informational citation field; verified in
`test_pfz_available_is_carried_but_never_affects_score` that two runs with identical
numeric inputs but opposite PFZ labels (`"favorable"` vs `"unfavorable"`) produce an
**identical** ORCA score — the official PFZ signal never leaks into ORCA's own
arithmetic. Since Phase 1 did not acquire a real PFZ snapshot, every `PFZReference`
constructed today has `status="unavailable"`, honestly, not a fabricated location.

## 8. Policy & Safety Guard (architecture.md §12, §23)

Outcomes (verbatim `SafetyGuardResult` contract from §12):
`PASS | BLOCK_BOUNDARY | BLOCK_MISSING_DATA | BLOCK_LOW_CONFIDENCE | BLOCK_HAZARD`.

**Precedence — taken verbatim from architecture.md §23's own pseudocode, in this exact
order:**

1. `has_boundary_violation` → `BLOCK_BOUNDARY`
2. `has_critical_missing_data` → `BLOCK_MISSING_DATA`
3. `confidence < min_confidence_threshold` → `BLOCK_LOW_CONFIDENCE`
4. `has_active_high_severity_advisory` → `BLOCK_HAZARD`
5. otherwise → `PASS`

**Note on an inconsistency between two parts of the source material**: the Phase 2 task
instructions' own conceptual summary describes hazard as the *second* check (right after
boundary). Architecture.md §23's actual code block checks it *last* — after low
confidence. Per this project's standing rule that the architecture document is the frozen
single source of truth, and the instruction to follow "the exact precedence... per the
architecture," this implementation uses §23's literal order. Both orderings are
exercised explicitly in `backend/tests/policy/test_safety_guard.py`
(`test_precedence_low_confidence_beats_hazard`, `test_precedence_boundary_beats_everything`).

`min_confidence_threshold` is referenced by architecture.md §23 as `CONFIG.min_confidence_threshold`
but is never given a numeric value anywhere in the architecture text. **Phase 2 default:
0.5**, stored in `risk_weights.yaml`'s `safety` section — a documented engineering
default, not a frozen architectural number.

## 9. Decision Engine (architecture.md §24)

Outcomes: `RECOMMEND | RECOMMEND_WITH_CAUTION | PROVIDE_ALTERNATIVES | NO_SAFE_RECOMMENDATION`.

```
Safety Guard outcome != PASS                          -> NO_SAFE_RECOMMENDATION  (always, regardless of risk/confidence)
LOW risk      + sufficient confidence (Guard == PASS) -> RECOMMEND
MODERATE risk + sufficient confidence (Guard == PASS) -> RECOMMEND_WITH_CAUTION
HIGH risk     + a safe alternative exists             -> PROVIDE_ALTERNATIVES
HIGH risk     + no safe alternative                   -> NO_SAFE_RECOMMENDATION
```

Note that **every** `BLOCK_*` Safety Guard outcome maps to `NO_SAFE_RECOMMENDATION` —
this is architecture.md §24's own mapping table, not a Phase 2 simplification;
`PROVIDE_ALTERNATIVES` is reached only through the `HIGH risk + Guard == PASS +
alternative exists` path. No natural-language explanation is generated here — that
remains the Evidence & Explanation Agent's job (§28, Phase 4+).

## 10. Hazard proxies (architecture.md §29a, §29b)

- **Lightning**: WMO weather codes 95-99 → `lightning_thunderstorm_proxy = 1.0`, exactly
  the range architecture.md §29b specifies. **This is a coarse thunderstorm proxy, not
  real-time lightning-strike detection.** DAMINI (IITM/IMD) remains the authoritative
  real-time system; ORCA has no live integration with it.
- **Cyclone**: `cyclone_proxy(pressure_tendency, sustained_wind, wind_gust,
  spatial_persistence, temporal_persistence)`, weighted combination
  (`cyclone_proxy_weights` in `risk_weights.yaml`, also fail-fast validated to sum to
  1.0 — an even split, since architecture.md §29a names the five signals but not their
  relative weight, documented as a Phase 2 starting point). **This is an ORCA hazard
  heuristic based on available weather-model signals — not authoritative cyclone
  identification or tracking.** Named `cyclone_proxy` in code, never `cyclone_detector`
  or `cyclone_tracker`, per §29a's explicit naming rule. RSMC New Delhi / IMD bulletins
  remain the authoritative reference.

## 11. LLM independence (structural, not conventional)

No module under `app/gis/`, `app/risk/`, `app/reasoning/`, `app/suitability/`,
`app/policy/`, or `app/decision/` imports any LLM SDK, calls any external LLM API, or
depends on `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY` in any way — every function in this
phase is fully unit-testable with zero network access and no API key
(`pytest -m "not integration and not live"` proves this: the entire Phase 2 suite runs
under that marker). Determinism is verified explicitly: every module has a test that
calls the same function with the same inputs multiple times and asserts an identical
result (see `test_determinism` in each test file, plus
`test_phase2_e2e.py::test_full_chain_is_deterministic` for the whole chain).

## 12. Missing-data behavior, summarized

| Layer | Behavior on missing input |
|---|---|
| `app.risk.components.*` | Raises `ValueError` — never substitutes 0 |
| `app.risk.engine.compute_risk` | Raises `MissingRiskComponentError`, naming every missing factor |
| `app.reasoning.confidence.ConfidenceInputs` | Pydantic rejects construction — no default for any of the 3 inputs |
| `app.policy.safety_guard` | Caller supplies `has_critical_missing_data: bool` explicitly; when `True`, `BLOCK_MISSING_DATA` fires regardless of what risk/confidence would otherwise say |

## 13. Testing

219 tests total. `pytest -m "not integration and not live"` (212 tests) requires no
network access and no infrastructure — this is the entire Phase 2 suite plus Phase 0/1's
offline tests. `pytest -m live` (3 tests) is Phase 1's real Open-Meteo regression.
`pytest -m integration` (4 tests) requires a live PostgreSQL/PostGIS/Redis instance —
unavailable in the development environment this phase was built in (see the Phase 2
implementation report for exact status).
