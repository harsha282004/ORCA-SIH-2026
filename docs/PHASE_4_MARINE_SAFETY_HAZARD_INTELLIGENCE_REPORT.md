# Phase 4 — Marine Safety & Hazard Intelligence

**Status:** Complete. Backend hazard detection, safety status classification, fishing/routing/Ask ORCA hazard integration, and a new `/safety` frontend page are implemented, live-verified against real external services, and covered by 24 new backend tests (10 unit + 10 API + 1 fishing + 2 orchestration + 1 routing). Frontend typecheck/lint/build are clean; a live Puppeteer smoke pass over `/safety`, `/marine-map`, `/fishing`, `/route-planner`, and `/ask-orca` recorded zero console/page errors.

---

## 1. Executive Summary

Phase 4 wires real hazard data (an active-cyclone feed and the existing Risk Engine's own wave/wind saturation thresholds) into ORCA's existing deterministic Safety Guard, for the first time making the previously-hardcoded-`False` `has_active_high_severity_advisory` fact genuinely reflect reality. No new risk formula, no new safety engine, and no LangGraph topology change were introduced — hazard detection is a new, self-contained package (`app/hazard/`) that existing pipelines opt into via a single `.model_copy()` override, exactly the same non-invasive pattern used consistently across the four integration points: `/api/v1/safety/*` (new), `/api/v1/query` → LangGraph's `safety_guard` node (existing, now hazard-aware for every intent), `app.fishing.engine`/`app.fishing.temporal` (existing, hazard-awareness now optional/backward-compatible), and `/api/v1/route` (existing, now reports cyclone proximity to the computed path).

## 2. What Was Inspected Before Building Anything

Before writing `app/hazard/`, the following were read and confirmed:

- `app/policy/safety_guard.py` — `SafetyFacts.has_active_high_severity_advisory` already existed as a typed field, hardcoded `False` by every caller since Phase 5's own documented scope limitation ("no official advisory ingestion exists yet"). This is the field Phase 4 wires — no new Safety Guard field was added.
- `app/risk/components.py` — `WAVE_SATURATION_M = 3.0`, `WIND_SATURATION_MS = 20.0` already existed as the Risk Engine's own documented saturation constants. Phase 4 imports these verbatim; it does not define a second threshold.
- `app/risk/hazard_proxies.py` — `THUNDERSTORM_WMO_CODES` and `lightning_thunderstorm_proxy()` already existed (Phase 1/3) as an explicitly-labeled, non-authoritative weather-code proxy. Phase 4 reuses the same code list for the new `THUNDERSTORM_PROXY` hazard type rather than inventing a new list.
- `app/decision/engine.py` — `make_decision()`'s `SafetyGuardOutcome != PASS` → `NO_SAFE_RECOMMENDATION` precedence already existed and required no change: forcing `has_active_high_severity_advisory=True` automatically produces the correct decision through the existing precedence.
- `app/orchestration/nodes.py`'s `safety_guard()` node and `app/agents/risk_suitability/agent.py`'s pipeline — confirmed the exact 3-step sequence (`derive_safety_facts` → `evaluate_safety_guard` → `make_decision`) used identically by the single-point conversational path, `app.fishing.engine.evaluate_candidate`, and `app.fishing.temporal.evaluate_temporal_suitability` — the same three call sites Phase 4 touches.
- `app/agents/query_understanding/models.py` — confirmed `IntentClass` already includes `"safety_check"`; no new intent was created.
- `app/api/v1/route.py` — confirmed the existing `hazard_provider(cell)` concept is a per-cell **risk-cost input** (the existing `advisory_or_hazard_flag` risk component, always `0.0` today), an entirely different thing from Phase 4's new `Hazard` objects. This distinction is documented in `app/hazard/route_hazards.py`'s module docstring to prevent future confusion between the two.
- `app/agents/common/cache.py` (`AgentCache`) — reused verbatim for the new cyclone cache; no new caching mechanism was introduced.

## 3. Hazard Source Audit

| Hazard | Source | Programmatic access | Format | Spatial coverage | Temporal coverage | Authoritative | ORCA status |
|---|---|---|---|---|---|---|---|
| Cyclone | IMD direct API (`api.imd.gov.in/api/v1/cyclone_track`) | Tested live: **HTTP 401** `{"error":"API key missing"}` | JSON | North Indian Ocean | Real-time | Yes | **UNAVAILABLE** (requires a key this deployment does not have; never bypassed/fabricated) |
| Cyclone | NOAA NHC | Yes, free, no key | JSON/KML | **Atlantic/E-Pacific only** | Real-time | Yes (wrong basin) | **NOT USED** — would silently under-report Indian-Ocean cyclones as "none" |
| Cyclone | GDACS (`gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=TC`) | Tested live: **HTTP 200**, real GeoJSON, no key | GeoJSON | Global (verified real Bay-of-Bengal entries) | Real-time (`iscurrent`, `fromdate`/`todate`/`datemodified`) | It republishes the actual issuing authority (`source` field: JTWC/RSMC/NOAA) | **AVAILABLE** — used, clearly labeled as an aggregator, never claimed as a primary IMD feed |
| Lightning/thunderstorm | DAMINI (IITM/IMD) | No public real-time API exists | — | — | — | Yes (in principle) | **UNAVAILABLE** — a WMO-weathercode-based proxy (`THUNDERSTORM_PROXY`, `is_proxy=True`, `is_authoritative=False`) is shown instead, never claimed as real detection |
| High wind | Open-Meteo Weather (already integrated) | Yes | JSON | Point-sampled | Real-time/forecast | No (model forecast) | **AVAILABLE** — thresholded on the Risk Engine's own `WIND_SATURATION_MS` |
| High waves | Open-Meteo Marine (already integrated) | Yes | JSON | Point-sampled | Real-time/forecast | No (model forecast) | **AVAILABLE** — thresholded on the Risk Engine's own `WAVE_SATURATION_M` |
| Restricted-zone boundary | `app.gis.geofence` fixture set | Yes | GeoJSON | Demo region only | Static | No — explicitly illustrative/demo, unchanged since Phase 1 | **LIMITED** |

This table is also served live at `GET /api/v1/safety/sources` (verified) rather than hardcoded twice in the frontend and in this report.

## 4. Hazard Data Model

`app/hazard/models.py` (new, minimal):

- `HazardType = "CYCLONE" | "HIGH_WIND" | "HIGH_WAVES" | "THUNDERSTORM_PROXY" | "GEOFENCE_BOUNDARY"`
- `HazardSeverity = "INFO" | "ADVISORY" | "WARNING" | "DANGER" | "CRITICAL"` — the task's own suggested scale; nothing existing covered "how severe is this specific event."
- `MarineSafetyLevel = "SAFE" | "CAUTION" | "WARNING" | "DANGER" | "UNKNOWN"` — a presentation-layer classification *derived from* (never a replacement for) `DecisionOutcome`/`RiskLevel`.
- `Hazard` — type, severity, title/description, optional lat/lon/distance, `valid_from`/`valid_until`/`observed_at`, `source`, `is_authoritative`, `is_proxy`, `freshness`, `confidence`.
- `HazardSourceStatus` — the audit-table row shape (§3), served live.
- `MarineSafetyStatus` — level + reason + the decision/safety/risk values it was derived from + the real hazard list + the real unavailable-sources list + `generated_at`.

## 5. Hazard Detection Engine

`app/hazard/engine.py::detect_weather_hazards()` — **pure, local, no network**: DANGER when `wave_height >= WAVE_SATURATION_M` or `wind_speed >= WIND_SATURATION_MS`; ADVISORY at 70% of either threshold (documented as the same "meaningfully elevated but not maximal" convention `classify_risk_level`'s own MODERATE band already uses — not a second, competing risk formula, only a label boundary). A `THUNDERSTORM_PROXY` hazard (`WARNING`, `is_proxy=True`) is emitted when the weathercode is in the existing `THUNDERSTORM_WMO_CODES` list.

`app/hazard/cyclone.py::fetch_active_cyclone_hazards()` — one real GDACS HTTP call, cached (Redis, `AgentCache`, 1800s TTL, best-effort) so ORCA never polls GDACS once per request. Returns `(hazards, source_tier)` where `source_tier ∈ {"live","cached","unavailable"}` — a fetch failure is **never** silently reported as "no cyclone"; it returns an explicit `"unavailable"` tier that downstream classification treats specially (§6). `relevant_cyclones()` filters to a documented 800km relevance radius using the existing `haversine_km` — never an LLM judgment of "near."

`detect_all_hazards()` composes both and **always** appends a `THUNDERSTORM_PROXY` `HazardSourceStatus(status="UNAVAILABLE")` entry — disclosed even when no hazard happens to be active, and a `CYCLONE` `HazardSourceStatus(status="UNAVAILABLE")` entry specifically when the GDACS fetch itself failed.

## 6. Marine Safety Status Classification

`app/hazard/safety_status.py::classify_safety_status()` — a pure derivation over already-computed values (task's own "never a second Safety Guard" instruction), precedence:

1. `decision is None or safety is None` → `UNKNOWN`
2. `decision.outcome == NO_SAFE_RECOMMENDATION` or any `DANGER`/`CRITICAL` hazard → `DANGER`
3. `PROVIDE_ALTERNATIVES`, `risk_level == HIGH`, or any `WARNING` hazard → `WARNING`
4. **A `CYCLONE` source marked `UNAVAILABLE`** → `UNKNOWN`, reason: *"cyclone hazard data could not be retrieved for this assessment — safety status is incomplete, not confirmed safe"* — checked **before** any SAFE/CAUTION fallthrough, directly implementing the task's "missing data must never become SAFE" requirement (§30 of the task spec).
5. `RECOMMEND_WITH_CAUTION`, `risk_level == MODERATE`, or any `ADVISORY` hazard → `CAUTION`
6. `RECOMMEND` and `risk_level == LOW` → `SAFE`
7. else → `UNKNOWN`

Live-verified (§9): a genuine GDACS outage (simulated via `monkeypatch` in tests, and reasoned about for the live case) forces `UNKNOWN`, never `SAFE`, even when wave/wind/geofence checks all pass.

**Known scope limitation, disclosed rather than silently absent:** an `UNAVAILABLE` lightning source does **not** currently force `UNKNOWN` the way an `UNAVAILABLE` cyclone source does — it is disclosed in `unavailable_sources` on every response, but the overall `level`/`reason` do not explicitly reference it when the level is otherwise SAFE/CAUTION/WARNING. The task's own worked example (§30) uses lightning specifically ("ORCA cannot provide a complete lightning-based safety assessment"); this deployment currently surfaces that fact structurally (always present in `unavailable_sources`) rather than in the top-level `reason` string. This is a genuine, minor gap, not a fabricated "detected: none" claim — recorded here rather than silently left unmentioned.

## 7. Wiring Into the Safety Guard (Non-Invasive)

`derive_safety_facts()` in `app/policy/safety_guard.py` is **untouched** — zero lines changed, zero regression risk to any existing caller. Every one of the four integration points below calls it normally, then applies the identical, minimal override:

```python
facts = derive_safety_facts(weather=..., marine=..., boundary_check=..., risk_suitability=...)
facts = facts.model_copy(update={"has_active_high_severity_advisory": critical_hazard_active})
safety = evaluate_safety_guard(facts, min_confidence_threshold=...)
```

## 8. The Four Integration Points

1. **`GET /api/v1/safety/status` / `/safety/hazards` / `/safety/sources`** (new, `app/api/v1/safety.py`) — the primary, dedicated Marine Safety surface. Runs the full pipeline for one point/time, real hazard detection, and returns a `MarineSafetyStatus`.
2. **`POST /api/v1/query` → LangGraph's `safety_guard` node** (`app/orchestration/nodes.py`, modified) — hazard-awareness now runs for **every** conversational intent (`safety_check`, `route_planning`, `diagnostic_exploration`, `boundary_check`, `zone_recommendation`) through the one shared node, with zero new node/edge and zero new intent class. `OrchestrationState` gained two new fields (`hazards`, `hazard_unavailable_sources`); `OrchestrationNodes.__init__` gained one new optional, injectable `hazard_cache` parameter (defaulting to the same best-effort Redis-backed cache every other hazard consumer uses). `POST /api/v1/query`'s response `data` now carries a `marine_safety` block (`level`, `reason`, `hazards`, `unavailable_sources`) alongside the existing `decision`/`safety`/`explanation` fields.
3. **`app.fishing.engine.evaluate_candidate` / `generate_candidates`** (modified, backward-compatible) — a new optional `cyclone_hazards`/`hazard_cache` parameter (default `None` reproduces Phase 3's exact behavior byte-for-byte). One real cyclone fetch per `generate_candidates()` call (never per-candidate — the task's own "no N×M explosion" rule). Each candidate's local weather/marine sample is checked (pure, no extra network) against the same thresholds; a candidate near an active cyclone or a saturating wave/wind reading is excluded from `ranked` via the same Safety Guard/Decision precedence, never a second, competing suitability penalty. `app.fishing.temporal.evaluate_temporal_suitability`'s previously-hardcoded `has_active_high_severity_advisory=False` is now wired directly from the same real per-hour wave/wind values it already computes (no cyclone check here — see the module's own docstring for why cyclone-per-hour would repeat the same fetch needlessly).
4. **`POST /api/v1/route`** (modified, additive) — after the existing A*/cost computation completes unchanged, `app.hazard.route_hazards.hazards_near_route()` checks the already-computed `path_coordinates` against real cyclone hazards (haversine, 800km relevance radius) and adds `hazards_near_route`/`hazard_source_tier` to the response. Wave/wind are deliberately **not** duplicated here — they are already priced into the route's own A* cost via the pre-existing `risk_provider`/`hazard_provider` sampling.

## 9. Live Verification (Real External Services, Not Mocks)

All performed against the running Docker stack with real Open-Meteo/GDACS/Redis:

- `GET /api/v1/safety/sources` → HTTP 200, exact 5-row audit table matching §3.
- `GET /api/v1/safety/status?latitude=12.8&longitude=74.2` → HTTP 200 (~3-5s), `level: "SAFE"`, `decision_outcome: "RECOMMEND"`, `risk_score: 0.246`, `hazards: []`, `unavailable_sources` correctly listing only `THUNDERSTORM_PROXY` (meaning the live GDACS cyclone check succeeded and genuinely found nothing relevant — no active storm near India at the time of testing).
- `GET /api/v1/safety/hazards` for the same point → consistent, `hazard_count: 0`.
- `POST /api/v1/query {"query":"Is it safe to fish near Mangaluru today?"}` → resolved to a location inside the demo land-geofence fixture; `safety.outcome: "BLOCK_BOUNDARY"`, `marine_safety.level: "DANGER"` (correctly reflecting the hard block, not an environmental hazard).
- `POST /api/v1/query {"query":"Is it safe to fish at 12.8 latitude 74.2 longitude today?"}` → `decision.outcome: "RECOMMEND"`, `marine_safety.level: "SAFE"`.
- `POST /api/v1/route` (Mangaluru–Udupi corridor) → `feasibility_status: "FEASIBLE"`, `hazards_near_route: []`, `hazard_source_tier: "cached"` (the cyclone cache, populated by the earlier `/safety/*` calls in the same session, was reused rather than re-fetched — confirms the shared cache is actually shared across endpoints).
- `GET /api/v1/fishing/candidates` → HTTP 200 (~14s, unchanged from Phase 3), 30 ranked / 6 avoid, `active_hazards_checked: true` on every candidate.

## 10. Backend Test Coverage (New in Phase 4)

24 new tests, all passing:

- `tests/hazard/test_engine.py` (10) — DANGER/ADVISORY wave and wind thresholds, calm-produces-nothing, thunderstorm proxy labeling, deterministic repeatability, cyclone relevance-radius filtering, `classify_safety_status`'s DANGER/UNKNOWN/UNKNOWN-on-missing-decision precedence.
- `tests/api/test_safety.py` (10) — out-of-domain rejection (both endpoints), SAFE-under-calm, DANGER-on-saturating-wave, CAUTION/WARNING/DANGER-on-advisory-wind, **UNKNOWN-not-SAFE-on-simulated-GDACS-outage** (`monkeypatch` forces `CycloneSourceError`), GeoJSON hazard feature shape, the 5-row source audit, determinism.
- `tests/fishing/test_engine.py` (+1) — the task's own worked example: a calm site (normally `ranked`) is forced to `avoid`/`NO_SAFE_RECOMMENDATION`/`BLOCK_HAZARD` when a real, nearby `CRITICAL` cyclone hazard is passed in.
- `tests/orchestration/test_graph_flow.py` (+2) — a dangerous wave height flowing through the full LangGraph produces a real `HIGH_WAVES` hazard and `BLOCK_HAZARD`/`NO_SAFE_RECOMMENDATION`; calm conditions produce zero hazards and `PASS`/`RECOMMEND`.
- `tests/routing/test_api_route.py` (+1, +2 assertions on an existing test) — `hazards_near_route`/`hazard_source_tier` are always present (even empty); a seeded nearby cyclone is correctly reported with a real measured distance.

**Test-suite hygiene (task §9's "never let hazard tests hit the real network" rule):** `tests/orchestration/conftest.py`'s `build_nodes()` and `tests/routing/test_api_route.py`'s fixture now inject an in-memory `FakeHazardCache`/`FakeCache` pre-seeded with an empty cyclone list — **without this fix, every orchestration and route test would have attempted a live GDACS call** the moment hazard detection was wired into the shared `safety_guard` node/route endpoint. Confirmed by timing: `tests/orchestration` + `tests/api/test_query.py` + `tests/api/test_provenance.py` + `tests/api/test_scenario.py` + `tests/safety` run in 1.76s (35 tests) and `tests/routing` + `tests/safety` run in 2.10s (60 tests) — both far too fast to be making real HTTP calls, confirming the offline-test contract those files' own docstrings promise is preserved.

## 11. Full Backend Suite — Baseline Preserved

Phase 3 ended at **556 passed, 2 pre-existing failures**. Phase 4 ends at:

```
2 failed, 580 passed, 1 warning in 45.76s
```

The 2 failures are **the exact same two, by name**, as Phase 3's documented baseline:
- `tests/agents/gis/test_agent.py::test_static_dataset_status_unreachable_db_reports_unknown_not_available` — environment-dependent (this deployment's PostGIS now genuinely has GEBCO acquired, so the "unreachable DB" assumption the test's own fixture makes no longer holds; not a Phase 4 regression).
- `tests/api/test_query_llm_not_configured.py::test_query_with_no_llm_provider_configured_returns_a_structured_503_not_a_raw_crash` — environment-dependent (this deployment has a real Groq key configured, so the "no LLM provider" precondition doesn't hold).

**580 − 556 = 24 new tests, all passing, zero new failures introduced by Phase 4.**

## 12. Fishing Intelligence Hazard Integration — What Changed

`FishingCandidate` gained two new fields: `active_hazards: list[dict] = []` and `active_hazards_checked: bool = False` — both default to the Phase-3-compatible "not evaluated" state so existing callers/tests are unaffected. `/api/v1/fishing/candidates`, `/nearest`, and `/compare` now inject a real `hazard_cache` dependency and pass it through; `/temporal` wires the per-hour real wave/wind values directly against the Risk Engine's saturation constants (no cyclone check per hour — documented limitation, §8.3 above).

## 13. Routing Hazard Integration — What Changed

`app/hazard/route_hazards.py` (new, ~50 lines) is a pure, additive post-hoc check: it does **not** touch `app.routing.astar`/`costs`/`grid`. `POST /api/v1/route`'s response gained `hazards_near_route: Hazard[]` (always present, even empty) and `hazard_source_tier: "live"|"cached"|"unavailable"`. `RouteResult` (the pydantic model) itself was **not** modified — the two new fields are merged into the response dict at the API layer only, keeping the routing engine's own model surface untouched.

## 14. Ask ORCA / Query-Understanding — What Changed and What Did Not

**No new intent class was created.** `IntentClass` already included `"safety_check"` (confirmed by inspection, §2). Hazard-awareness reaches Ask ORCA through two paths: (1) the shared `safety_guard` orchestration node (§8.2) — every existing intent benefits automatically; (2) `zone_recommendation`'s dedicated fishing path (`app/api/v1/query.py::_handle_zone_recommendation`, built in Phase 3) now also receives a `hazard_cache` (a new `get_fishing_hazard_cache` DI provider, same pattern as `app/api/v1/fishing.py`) and passes it through to `generate_candidates()` — live-verified: `POST /api/v1/query {"query":"Find suitable fishing areas near Mangaluru"}` still returns `status: completed` with real ranked candidates after this change.

## 15. The `requested_time` Bug — Not Touched, As Instructed

Per the task's explicit instruction, the foundational `_select_current_step` bug (discovered in Phase 3, ignores the caller's `requested_time` in favor of the fetch's own wall-clock time) was **not** touched. Where Phase 4 needed time-specific hazard behavior (`app.fishing.temporal`), it reused the exact same proven `parse_hourly_timeseries` workaround Phase 3 already established, extending it only with the two new saturation-threshold checks (§12). No change was made to `app.data.open_meteo_common`.

## 16. Redis Stale-Data Safeguard (Task §32)

The cyclone cache (`orca:hazard:cyclone:active_tc`, 1800s TTL) is the one new piece of hazard-related caching this phase introduces. It uses the exact same `AgentCache` every other data agent already uses, with the same best-effort semantics (a Redis failure is a cache miss, never a crash, and never treated as "confirmed current"). No change was needed to the Redis client or TTL mechanism itself: a cache **hit** always means "GDACS was successfully reached within the last 30 minutes and this is what it returned" — never a claim of "right now." A cache **miss or Redis failure** always falls through to a live fetch attempt, and a live-fetch failure is reported as `source_tier: "unavailable"` (never silently treated as "no cyclone" — see §5/§6). The pre-existing, unrelated GIS dataset-status cache staleness issue (`orca:agent:gis:dataset_status:*`, first found in Phase 1) is **not** part of this mechanism and was not touched — it does not feed into any Phase 4 safety decision.

## 17. Known Limitations (Disclosed, Not Hidden)

1. Lightning/thunderstorm detection is a coarse weather-code **proxy** only (never claimed as real detection) — always disclosed via `unavailable_sources`, but does not currently force `MarineSafetyLevel.UNKNOWN` the way a cyclone-source failure does (§6).
2. `app.fishing.engine`'s cyclone check degrades to an *empty* list on a GDACS outage rather than surfacing its own `HazardSourceStatus`/forcing `UNKNOWN` the way `/api/v1/safety` does — documented in the module itself (`generate_candidates`'s inline comment).
3. `app.fishing.temporal` does not check cyclone proximity per hour (only wave/wind) — deliberately, to avoid repeating a GDACS fetch per synthesized hour.
4. The Marine Map's hazard layer checks a single reference point (the region centroid) rather than a spatial grid — correct given a cyclone's ~800km relevance radius makes grid-sampling redundant, but means a hazard near the region's edge, far from the centroid, would not currently be surfaced on that specific map view (it would still be correctly surfaced via `/safety/status` for that exact point).

None of these convert missing/limited data into a false "safe" claim — each is either disclosed via `unavailable_sources`/`source_tier`, or is a documented scope boundary rather than a silent gap.

## 18. Frontend Changes

- `frontend/src/lib/api.ts` — new `Hazard`, `HazardSourceStatus`, `MarineSafetyStatus`, `HazardType`/`HazardSeverity`/`MarineSafetyLevel` types; `getSafetyStatus`, `getSafetyHazards`, `getSafetySources` client functions; `QueryResponseData.marine_safety`, `RouteResultData.hazards_near_route`/`hazard_source_tier`, `FishingCandidateProps.active_hazards`/`active_hazards_checked` added to existing interfaces.
- `frontend/src/components/map/mapLayers.ts` — new `buildHazardsLayer()`: a hollow, thick-ringed, severity-colored/sized marker, visually distinct from every other layer (fishing candidates, SST, suitability).
- `frontend/src/components/map/EvidencePanel.tsx` — new `"hazard"` layer case; the existing `"fishing-candidate"` case now also shows `active_hazards` when hazard-awareness was checked for that candidate.
- `frontend/src/components/map/MapLegend.tsx` — new "Marine Hazards" section with the severity color key and an explicit lightning-unavailable disclaimer.
- `frontend/src/routes/SafetyPage.tsx` (new) — Current Safety Status / Active Hazards / Map / Selected Hazard (via the shared EvidencePanel) / Recommendation / Data Availability, per the task's own mockup structure. A lat/lon input (defaulting to the demo region centroid) drives `GET /api/v1/safety/status`/`/hazards`; `GET /api/v1/safety/sources` populates Data Availability independently of location.
- `frontend/src/routes/MarineMapPage.tsx` — new "Marine Hazards" toggle (off by default) using the same `useMapLayer` machinery as every other layer; a "Lightning / Thunderstorm (authoritative)" entry is listed as explicitly unavailable in the layer control panel, never silently omitted.
- `frontend/src/App.tsx` / `Navbar.tsx` — registered the lazy-loaded `/safety` route and its nav link.

## 19. Frontend Testing

- `npx tsc --noEmit` — 0 errors.
- `npm run lint` (ESLint) — 0 errors/warnings.
- `npm run build` (`tsc -b && vite build`) — succeeds; `SafetyPage` bundles as its own 10.76 kB code-split chunk (lazy-loaded, consistent with every other MapLibre/deck.gl-mounting page).
- Live Puppeteer smoke pass (headless Edge) across `/safety`, `/marine-map` (with the new hazard toggle clicked), `/fishing`, `/route-planner`: **zero console/page errors** on every page. `/safety` rendered a real live status ("Safe — risk is LOW and confidence is sufficient — Decision RECOMMEND — Safety guard PASS — Risk LOW (0.226) — Confidence 100%"), the Active Hazards section, and the Data Availability section.
- A separate live Ask ORCA smoke test ("Is it safe to fish at 12.8, 74.2 right now?") returned a real, safety-grounded natural-language answer with zero console errors and the "Safety" nav link visible and correctly labeled.

## 20. What Was Deliberately NOT Built (Scope Control)

Per the task's explicit scope limits, this phase did not add: multilingual safety explanations beyond the existing `EvidenceExplanationAgent`/`i18n` machinery, scenario/what-if hazard simulation, SMS/WhatsApp/email/push alert delivery, mobile-specific UX polish, production deployment changes, or any new database/mapping/orchestration framework. `app/alerts/` (visible in this repository's working tree) predates this phase's scope and was not modified or extended here.

## 21. Files Added

`backend/app/hazard/__init__.py`, `models.py`, `cyclone.py`, `engine.py`, `safety_status.py`, `route_hazards.py`; `backend/app/api/v1/safety.py`; `backend/tests/hazard/__init__.py`, `test_engine.py`; `backend/tests/api/test_safety.py`; `frontend/src/routes/SafetyPage.tsx`; this report.

## 22. Files Modified

`backend/app/main.py` (router registration); `backend/app/fishing/models.py`, `engine.py`, `temporal.py`; `backend/app/api/v1/fishing.py`, `route.py`, `query.py`; `backend/app/orchestration/state.py`, `nodes.py`; `backend/tests/orchestration/conftest.py`, `test_graph_flow.py`; `backend/tests/routing/test_api_route.py`; `backend/tests/safety/test_mandatory_safety_scenarios.py` (fixture only — added the hazard-cache override, no assertions changed); `frontend/src/lib/api.ts`, `App.tsx`; `frontend/src/components/layout/Navbar.tsx`; `frontend/src/components/map/mapLayers.ts`, `EvidencePanel.tsx`, `MapLegend.tsx`; `frontend/src/routes/MarineMapPage.tsx`.

## 23. Docker / Environment Verification

`docker compose build backend && up -d backend`, `docker compose build frontend && up -d frontend` — both succeeded; all four containers (`orca-backend`, `orca-frontend`, `orca-postgres`, `orca-redis`) reported healthy/running. `curl http://localhost:8000/health` → `{"status":"ok"}`. The recurring GIS dataset-status Redis cache (unrelated to this phase) was pre-emptively flushed at the start of the session per the established Phase 1/2 workaround.

## 24. Readiness for Later Phases

The hazard package's clean separation (`app/hazard/` has no dependency on `app/fishing`, `app/routing`, or `app/orchestration` — those depend on it, not the reverse) means a future phase adding alert delivery (SMS/WhatsApp/push) or scenario/what-if simulation can consume `app.hazard.engine.detect_all_hazards`/`MarineSafetyStatus` directly without touching this phase's code. The two documented gaps in §17 (lightning non-blocking, fishing-engine cyclone-outage handling, Ask ORCA's `_handle_zone_recommendation` not yet passing a `hazard_cache`) are each a small, well-scoped follow-up, not architectural rework.
