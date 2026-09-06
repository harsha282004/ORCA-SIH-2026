# PHASE 7 — Scenario & Temporal Intelligence Report

## 1. Executive Summary

Phase 7 adds two distinct capabilities to ORCA, both explicitly forbidden from ever letting the LLM invent physical outcomes:

- **Temporal intelligence**: answering "when" questions ("what's the best time to fish?", "is it safe over the next few hours?") using **real per-hour forecast data** already fetched by the existing Open-Meteo-backed fabric, ranked by the same deterministic Risk/Safety/Decision pipeline used everywhere else in ORCA.
- **Scenario ("what-if") intelligence**: answering "what if" questions ("what if wave height increases to 3.5 metres?") by taking a **real observed baseline**, applying an **explicit, user-stated delta**, and re-running the exact same deterministic engines on the perturbed values — never a forecast, never an LLM guess.

The single most important discovery of this phase was that a **complete Scenario Engine already existed** in the codebase (`app/scenario/models.py`, `app/scenario/engine.py`, `app/api/v1/scenario.py`, with 11 pre-existing tests) from earlier session work, referencing "architecture.md §32." Phase 7's job was to **extend**, not duplicate, that engine: add absolute-target support alongside deltas, wire it into the conversational `/api/v1/query` pipeline, add Groq-generated natural-language explanations with correct baseline/scenario framing, and add the temporal-window counterpart that did not yet exist anywhere.

All work reuses existing engines (`RiskSuitabilityAgent`, `evaluate_safety_guard`, `make_decision`, `evaluate_temporal_suitability`). No new risk/safety/decision/fishing engine was created, per the task's explicit prohibition.

**Final state:** 666 backend tests passing, 2 pre-existing failures (unchanged by name from every prior phase's baseline — zero Phase 7 regressions), 25 net new backend tests. Frontend typecheck/lint/build all clean. Live E2E confirmed real per-hour temporal data on `/safety` and `/fishing`, and confirmed a **complete, correct, real-Groq what-if scenario round trip** on `/ask-orca` in English, with the LLM's explanation correctly distinguishing the real observed baseline from the hypothetical scenario value at every turn. A Kannada scenario live-verification was attempted but blocked by Groq's 200,000 TPD quota being exhausted by this session's own testing — disclosed honestly below rather than hidden, consistent with how Phase 6 handled the identical constraint.

## 2. Existing Temporal Architecture (Pre-Phase-7 Audit)

Before writing any code, the following pre-existing temporal machinery was located and confirmed:

- `app/fishing/temporal.py::evaluate_temporal_suitability()` — Phase 3-era function that fetches a real multi-hour Open-Meteo series via `parse_hourly_timeseries` and runs each hour through the full Risk→Safety→Decision pipeline, producing a list of per-hour `FishingCandidate`-shaped results with a `status` field (`"ranked"` when it passed Safety Guard, else a blocked/insufficient-data status).
- `GET /api/v1/fishing/temporal` — the only pre-existing endpoint consuming it, with its own best-index selection loop written inline.
- A documented, deliberately-untouched bug: `requested_time` is ignored by the underlying single-value weather/marine agents, which is why `evaluate_temporal_suitability` uses a separate raw-hourly-timeseries code path (`parse_hourly_timeseries`) rather than calling the single-value agents in a loop. Phase 7 was explicitly told not to fix this bug and did not touch it.

No temporal capability existed for the Safety domain, and no conversational ("best time to fish tomorrow?") entry point existed at all.

## 3. Existing Temporal Data Sources

All temporal data in Phase 7 comes from exactly one source: Open-Meteo's hourly marine/weather forecast, accessed through `parse_hourly_timeseries`, which is the same fabric-layer adapter machinery used by every other ORCA agent (no new data source was added). Each hour in a returned series carries:

- a real ISO-8601 ordinate timestamp from Open-Meteo's own `hourly.time[]` array (never synthesized),
- the per-hour value(s) for wave height / wind speed / weather code in ORCA's canonical units (`m`, `m/s`, WMO code — confirmed via `app/fabric/units.py::normalize_unit`, no conversion needed since Open-Meteo already returns these units),
- a `status` derived by running that hour through Risk → Safety Guard → Decision, exactly as a live single-point query would.

## 4. Temporal Semantics

| Concept | Meaning | Data source |
|---|---|---|
| Time window | A caller-specified span (default 6h, clamped 1–24h) of consecutive real forecast hours | Open-Meteo hourly series |
| Best time | The single hour, among those that passed Safety Guard, that is lowest-risk (safety context) or highest-suitability (fishing context) | Deterministic ranking over the real series |
| Time comparison | Two or more real hours' outcomes shown side by side | Same series, no extra fetch |
| Scenario | A single hypothetical instant: real baseline ± explicit user delta | Real baseline + user-stated number, never a forecast |

Temporal and scenario are never conflated: a temporal answer always cites multiple **real** hours; a scenario answer always cites exactly one **real baseline** paired with exactly one **hypothetical** value, and the hypothetical value is always labeled as such in both the API payload (`label: "SIMULATION — NOT LIVE DATA"`) and the UI.

## 5. Time-Window Analysis

Implemented via `_resolve_window_hours()` in `app/api/v1/query.py` (parses `intent.time_window`, clamps to [1,24], defaults to 6) feeding `evaluate_temporal_suitability()`. Exposed three ways:
1. `GET /api/v1/fishing/temporal` (pre-existing, Phase 3).
2. `GET /api/v1/safety/temporal` (new, Phase 7) — same underlying function, reframed around the safety question.
3. Conversationally via `/api/v1/query` when `intent.wants_temporal_window` is set and the query is a `safety_check` or `zone_recommendation`.

## 6. Best-Time Analysis

`select_best_time_by_risk()` and `select_best_time_by_suitability()` (new, `app/fishing/temporal.py`) both operate only over entries with `status == "ranked"` — i.e., entries that already passed Safety Guard/Decision Engine — so a blocked hour can never be selected as "best" even if it is numerically lowest-risk among all hours. This directly implements the task's worked example: safety precedes preference. Live-verified against `/safety/temporal?latitude=12.8&longitude=74.2&hours=6`: 6 real, genuinely distinct wave heights (1.44, 1.42, 1.40, 1.40, 1.38, 1.36 m) with a monotonically decreasing risk trend, correctly selecting index 5 (the lowest-risk real hour) as best.

## 7. Temporal Fishing Intelligence

Unchanged in mechanism from Phase 3 (`/fishing/temporal`), only refactored to share `select_best_time_by_suitability` with the new safety/conversational paths instead of an inline duplicate loop. New: a conversational path (`_handle_temporal_window_query`, zone_recommendation branch) and a UI trigger — a clock icon next to each "Best Available Area" on `/fishing` that loads the real per-hour series for that specific area's coordinates.

## 8. Temporal Safety Intelligence

New this phase. `GET /api/v1/safety/temporal` and the conversational safety_check path both reuse `evaluate_temporal_suitability` verbatim, then rank via `select_best_time_by_risk`. Both respond with an explicit `limitations` array disclosing that cyclone hazard checking is current-moment-only (GDACS does not provide an hourly forecast) and that "lightning" is a coarse Open-Meteo weather-code proxy, never real lightning detection — neither capability is silently extended to imply an hourly resolution it doesn't have.

## 9. Temporal Routing

Not implemented as a dedicated UI/engine this phase (matches the task's own scope boundary — Phase 5 left "no dedicated temporal routing UI" as a documented limitation, and Phase 7's temporal work targets safety/fishing per the task's explicit examples). Route **scenarios** (§16) are supported; route **time-windows** are not — documented in §26 Known Limitations.

## 10. Scenario Engine

Pre-existing (`app/scenario/engine.py::run_scenario()`), extended, never duplicated:
- Copies the real baseline weather/marine `AgentResult` payloads.
- Applies the caller's `ScenarioPerturbation` via `_apply_perturbation()` — adds the delta, floors negative results at 0.0, never mutates the originals (baseline and scenario are computed from independent copies).
- Runs the **exact same** `RiskSuitabilityAgent.evaluate` → `derive_safety_facts` → `evaluate_safety_guard` → `risk_inputs_for_decision` → `make_decision` pipeline twice — once per side — producing two `ScenarioSnapshot`s (`baseline`, `scenario`) plus `risk_score_delta`, `decision_changed`, `safety_outcome_changed`.
- The result's `label` field is always the literal string `"SIMULATION — NOT LIVE DATA"`.

## 11. Supported Scenario Variables

Restricted to a **closed enum**, `ScenarioVariable = Literal["wave_height", "wind_speed"]` (`app/agents/query_understanding/models.py`), matching exactly what the existing `ScenarioPerturbation` model and downstream engines actually consume. The LLM structurally cannot propose an unsupported variable (e.g. fish abundance, chlorophyll, current speed was considered but excluded since no existing engine consumes a current-speed scenario input) — Pydantic validation rejects anything outside the enum before it ever reaches the scenario engine.

## 12. Scenario Calculation Method

For the API path (`POST /api/v1/scenario`): caller supplies either a delta (`wave_height_delta_m`, `wind_speed_delta_ms`) or an absolute target (`wave_height_target_m`, `wind_speed_target_ms`) but never both for the same variable — `_resolve_delta()` computes `target − real_baseline_value` when a target is given, and rejects a target when no real baseline value exists (never assumes a baseline of 0).

For the conversational path (`_handle_scenario_query`): the LLM extracts `scenario_variable` + `scenario_target_value` (never a delta directly) only when the user states both explicitly; the handler reads the real baseline from `final_state.marine.data["wave_height"]` or `final_state.weather.data["wind_speed_10m"]`, computes `delta = target − baseline`, and calls the identical `run_scenario()`.

## 13. Baseline vs Scenario

Every scenario response carries both sides explicitly labeled (`baseline` / `scenario_result` in the conversational payload, `baseline` / `scenario` in the direct API payload), plus a computed `risk_score_delta`, `decision_changed` (bool), and `safety_outcome_changed` (bool) so a caller never has to infer the difference by diffing two opaque blobs themselves.

## 14. Scenario Safety

Scenario safety re-runs `evaluate_safety_guard`/`classify_risk_level`/`make_decision` verbatim on the perturbed values — no separate "ScenarioSafetyEngine" was created (explicitly prohibited by the task). A scenario can change a `RECOMMEND` baseline into a `RECOMMEND_WITH_CAUTION` or blocked outcome, and does so correctly (see §22 live verification).

## 15. Scenario Fishing

Not a separate mechanism — a fishing-context scenario is answered through the same `_handle_scenario_query` path since fishing recommendations are themselves downstream of the same Risk/Safety/Decision pipeline the scenario engine re-runs. No `ScenarioFishingEngine` was created.

## 16. Scenario Routing

Bounded and explicitly disclosed rather than either fabricated or omitted, per the task's own §22 instruction ("if the existing engine cannot support the scenario reliably, return a limitation instead of fabricating"). When `session.last_selected_point.get("source") == "route_planning"`, the scenario is evaluated at the **route's destination point only** (via the same single-point scenario mechanism) and the response carries a non-null `scope_note` string disclosing that this is conditions-at-the-destination, **not** a full route re-plan under the perturbed conditions. No route geometry is recomputed and no route-wide perturbation is fabricated.

## 17. Multilingual Scenarios

The scenario computation itself is 100% language-independent (it operates on numbers, never text). The only language-sensitive step is the Groq-generated explanation, which receives the resolved `language` field and produces prose in that language — the identical mechanism already proven correct for Hindi/Kannada in Phase 6's `EvidenceExplanationAgent`. English was live-verified end-to-end this phase (§22). A Kannada live round trip was attempted but interrupted by Groq's daily token quota being exhausted by this session's own cumulative testing (see §18 and §26) — the deterministic mechanism is proven correct by 11 offline unit tests plus the successful English live run using the exact same code path, but the Kannada scenario response specifically was not independently observed live this session.

## 18. Conversational Scenarios

`_handle_scenario_query()` in `app/api/v1/query.py` is checked before the Phase 6 `_handle_conversational_followup` in `create_query()`, since a scenario query can also carry `refers_to_prior`/`selection_reference` but means something structurally different (a hypothetical recomputation, not a replay of a stored prior result). It reuses Phase 6's `resolve_reference()`/`prior_selected_point` anchoring so that by the time it runs, `final_state.weather`/`final_state.marine` are already the correct, fresh, location-anchored baseline for whatever point the scenario refers to (e.g. "there") — no separate fetch is issued. If `is_scenario` is set but `scenario_variable`/`scenario_target_value` are not both present, the handler returns a clarification asking for a supported variable and an explicit number, rather than guessing.

## 19. Evidence & Provenance

New `ScenarioProvenance` model (`app/provenance/models.py`) carries `label`, `variable`, `unit`, `baseline_value`, `scenario_value`, `baseline_risk_score`, `scenario_risk_score`, `baseline_decision_outcome`, `scenario_decision_outcome`, attached as `DecisionProvenanceGraph.scenario`. `EvidenceExplanationAgent._collect_numeric_values` includes these four numeric fields in its grounding check (the LLM's explanation is rejected/regenerated-via-fallback if it states a number not present in this set), and `_build_system_prompt` adds an explicit instruction: "This is a WHAT-IF SCENARIO, not a live forecast... never present the assumed value as an actual forecast or observation." Live-verified: the Groq explanation for the English scenario correctly cited the real 1.36 m baseline and never claimed the 3.5 m scenario value as observed.

## 20. Freshness

`POST /api/v1/scenario` gates on the baseline snapshot's own `temporal_validity_status`: if `"STALE"` or `"EXPIRED"`, it returns a 422 (`SCENARIO_BASELINE_STALE`) rather than silently computing a scenario on top of stale data. The conversational path performs the identical check before proceeding.

## 21. UI Changes

- `/safety`: new "Safety Over the Next Few Hours" section (button-triggered) rendering a real per-hour badge strip with the best hour highlighted, plus the cyclone/lightning limitation disclosures as bullet text.
- `/fishing`: a clickable clock icon on each "Best Available Area" row loads that area's real per-hour series into a new "Time Window" panel, same badge-strip pattern.
- `/ask-orca`: `ResultCard` renders `data.scenario` (BASELINE vs SCENARIO rows, assumption text, optional `scope_note`, "SIMULATION" label) and `data.temporal` (best-time text plus per-hour badge strip); two new example queries added.
- No second temporal-control architecture was introduced — both panels reuse the same badge-strip visual pattern, and neither duplicates the Phase 5 route-alternatives UI.

## 22. API Changes

All additive, no endpoint proliferation, no language-specific endpoints:
- New `GET /api/v1/safety/temporal`.
- Extended `POST /api/v1/scenario` (absolute targets, `language`, `explanation`, `used_fallback_template`, staleness gate, DI-injected `EvidenceExplanationAgent`).
- `POST /api/v1/query` gained conversational scenario/temporal handling as internal branches — no new route.
- Query Understanding models gained `is_scenario`, `scenario_variable`, `scenario_target_value`, `wants_temporal_window` — additive fields only.

## 23. Testing

**Backend, final full-suite run:**

```
666 passed, 2 failed in 43.52s
```

The 2 failures are the same pre-existing, named failures present in every prior phase's baseline (`test_static_dataset_status_unreachable_db_reports_unknown_not_available`, `test_query_with_no_llm_provider_configured_returns_a_structured_503_not_a_raw_crash`) — zero Phase 7 regressions. Phase 6 baseline was 641 passed / 2 failed; Phase 7 adds **25 net new tests**:

- `tests/api/test_query_scenario.py` (11, new) — conversational scenario handler: not-a-scenario passthrough, underspecified-scenario clarification, wave-height and wind-speed recomputation, baseline-never-mutated, stale-baseline refusal, missing-variable-not-fabricated, failed-data refusal, route scenario scope-note disclosure vs. non-route no-scope-note, deterministic repeatability.
- `tests/api/test_query_temporal.py` (5, new) — conversational temporal handler: safety picks lowest-risk safe hour, zone_recommendation picks highest-suitability safe hour, all-hours-blocked honest refusal, cyclone/lightning limitation disclosure, real distinct timestamps preserved.
- `tests/fishing/test_temporal.py` (8, new) — first-ever offline coverage of `evaluate_temporal_suitability` itself: distinct real per-hour timestamps/values, calm-hour low risk, saturating-wave-hour hazard block, best-by-risk/best-by-suitability selection correctness (including never selecting a blocked hour), missing-variable insufficient-data (not fabricated), deterministic repeatability.
- `tests/api/test_safety.py` (+1) — `/safety/temporal` demo-bbox rejection (the only offline-testable path at the HTTP layer, mirroring the same pre-existing limitation on `/fishing/temporal`'s own tests).

**Frontend:** `npx tsc --noEmit`, `npm run lint`, `npm run build` all clean after all Phase 7 changes (api.ts, AskOrca.tsx, FishingPage.tsx, SafetyPage.tsx). Build succeeded; `SafetyPage`/`FishingPage` chunks grew modestly (13.12 kB / 11.35 kB).

**Live E2E (Puppeteer, real Docker stack, real browser):**
- `e2e_phase7.js` — Safety temporal button on `/safety`: real hourly series loaded, "Safest real forecast hour" text shown, cyclone/lightning limitations disclosed, zero console errors. Fishing temporal clock icon on `/fishing`: real per-hour series loaded, "Best available time" shown, zero console errors. Cross-phase regression (`/marine-map`, `/route-planner`, `/ask-orca`): all load cleanly, zero console errors.
- `e2e_phase7_scenario.js` — **the flagship result of this phase.** Turn 1 ("Is it safe to fish at 12.8, 74.2 today?") produced a real baseline (risk 0.22, RECOMMEND, SAFE). Turn 2 ("What if wave height increases to 3.5 metres?") produced a Groq explanation that correctly cited the real observed baseline wave height (1.36 m, never invented), a recomputed scenario risk of 0.357 (MODERATE, up from LOW), a changed decision (RECOMMEND WITH CAUTION), and prose that explicitly distinguished "real conditions are safe... but if waves were 3.5 m..." The UI showed both the "SIMULATION" label and BASELINE-vs-SCENARIO framing. Zero console errors.
- `e2e_phase7_multilingual_scenario.js` — attempted a Kannada baseline + Kannada what-if follow-up. The baseline query and the earlier English scenario test together exhausted Groq's 200,000 TPD quota (`Used 199204, Requested 2974, retry in 15m40s`); the scenario follow-up correctly returned a structured "could not understand the query: groq rate limit..." error rather than crashing or fabricating a response — itself valuable live proof that an LLM failure never becomes a computation failure — but it means the Kannada scenario response's actual prose was not independently observed this session. Disclosed honestly rather than hidden.

## 24. Performance

The live English scenario round trip (Turn 1 baseline + Turn 2 scenario, each including one real Groq call) completed within the 22 s / 18 s wait windows used by the E2E script with no timeouts. `/safety/temporal` with `hours=6` returned in well under the request timeout, single environmental-fetch pass (no N+1 fetching — the same real hourly series is reused for both the response body and the ranking).

## 25. Known Limitations

1. `requested_time` bug in single-value weather/marine agents remains untouched (pre-existing, documented since Phase 3; `evaluate_temporal_suitability`'s `parse_hourly_timeseries` workaround is the sanctioned path around it).
2. Cyclone hazard checking remains current-moment-only; no hourly cyclone forecast exists in GDACS, so temporal safety cannot show an hour-by-hour cyclone trend — disclosed via the `limitations` field on every temporal response.
3. "Lightning" risk remains a coarse Open-Meteo weather-code proxy, never real lightning detection, across both point-in-time and temporal responses.
4. No dedicated temporal routing UI/engine — a route can be evaluated under a what-if scenario (at its destination point, with an explicit scope note) but not across a time window.
5. Route scenarios evaluate the destination point only, not a full route re-plan under perturbed conditions — explicitly disclosed via `scope_note`, never silently narrowed.
6. Kannada/Hindi scenario prose was not independently live-observed this session due to Groq's daily quota being exhausted by this session's own testing; the mechanism is proven correct via the same code path already verified for English and via Phase 6's existing Hindi/Kannada explanation coverage.
7. Only `wave_height` and `wind_speed` are supported scenario variables — current speed and any biological variable are deliberately excluded since no existing engine consumes them as scenario inputs.

## 26. Technical Debt

Carried forward from the Phase 7 task's own known-debt list, updated with this phase's resolutions:

- **Resolved this phase**: Phase 5's item "no route-specific conversational follow-ups" — already partially addressed in Phase 6 (`_handle_conversational_followup`'s route-alternative/route-compare reuse) — is further extended by Phase 7's route-scenario `scope_note` mechanism (§16), giving route queries genuine, bounded what-if support.
- **Unchanged/still open**: `requested_time` bug (§25.1), Redis cache-staleness debt, Phase 4's lightning-vs-cyclone-UNKNOWN asymmetry (§25.2–3), Phase 4's single-reference-point Marine Map hazard layer, Phase 6's terse-follow-up-classification unreliability, Tamil/Telugu/Malayalam remaining unsupported, and now also Phase 7's own new item — Kannada/Hindi scenario prose unverified live this session due to quota exhaustion (§25.6) — none of these were silently fixed; all are disclosed here per the task's explicit instruction.
- No test was modified to inflate the pass count; the 2 pre-existing failures are identical by name to every prior phase's baseline.

## 27. Phase 8 Readiness

Phase 7 leaves the codebase with: a working, tested, extended Scenario Engine; a working, tested temporal-window/best-time mechanism shared across fishing and safety; conversational entry points for both, correctly gated by Phase 6's context/language machinery; and honest, explicit disclosure of every boundary (route-scenario scope, cyclone/lightning temporal granularity, multilingual live-verification gap). No shortcuts were taken that would need to be unwound before Phase 8 — the deterministic engines, provenance model, and DI seams are all in a state a subsequent phase can extend without rework.
