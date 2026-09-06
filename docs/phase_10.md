# Phase 7-10 — LLM Abstraction Extension, Provenance, and Advanced ORCA Capabilities

This document describes what is actually implemented for Phase 7-10. See
[`docs/architecture.md`](architecture.md) §11a, §27-§29, §31a, §32, §34 for the frozen
architecture this implements against, and [`docs/orchestration.md`](orchestration.md)
for Phase 5, which this phase extends without rebuilding.

## 1. Initial audit finding

Phases 7 (LLM Provider Abstraction + Query Understanding), 8 (LangGraph Orchestration),
and 9 (Provenance + Explanation) were found, on direct file-by-file audit, to already be
substantially implemented under Phase 5's structure (`app.llm.*`,
`app.agents.query_understanding.*`, `app.orchestration.*`, `app.provenance.models`,
`app.agents.evidence_explanation.*`). Per this project's frozen-architecture rule, none
of it was rebuilt. Two genuine gaps were found and closed:

- `IntentResult.refers_to_prior`/`reference_type` were populated by the LLM but never
  actually acted on deterministically — `OrchestrationState` had no `prior_intent`
  input field and `POST /api/v1/query` never passed `session.last_intent` in. Fixed in
  §2 below.
- `GET /query/{id}/provenance` (architecture §34) did not exist — provenance was only
  ever retrievable embedded in a `/query` response. Fixed in §5 below.

Phase 10 (route comparison, multi-turn interaction, scenario analysis, alerts, maritime
decision support) is covered in §2-§4.

## 2. Multi-turn reference resolution (architecture §31a)

```
LLM interpretation (structured reference only: refers_to_prior, reference_type,
                     reference_delta.offshore_distance_km)
        |
app.agents.query_understanding.reference.resolve_reference()
        |
Deterministic offset via app.gis.distance.offset_point_km()
        |
Resolved IntentResult re-enters the pipeline
```

- `RawIntentResult`/`IntentResult` gained one new optional field, `reference_delta:
  ReferenceDelta | None` (`{offshore_distance_km: float | None}`) —
  architecture §31a's own worked example, and nothing beyond it. Named `reference_delta`
  rather than "relative change" specifically so the field name itself cannot trip
  `test_raw_intent_schema_has_no_coordinate_or_absolute_timestamp_fields`'s substring
  guard (`"relative_change"` contains `"lat"` as a substring of "re**lat**ive").
- `app.gis.distance.offset_point_km()` — a new deterministic function reusing the exact
  equirectangular-projection approximation `distance_to_polygon_km` already established
  (111.32 km/deg latitude, `cos(latitude)`-scaled km/deg longitude).
- `app.agents.query_understanding.reference.resolve_reference(intent, prior_intent, *,
  demo_bbox)` — pure, deterministic. A no-op unless `intent.refers_to_prior` and a
  `prior_intent` both exist. Handles two cases: an offshore-distance follow-up (computes
  a new bbox centered on the prior turn's location, clamped to `demo_bbox` exactly as
  `location.py`'s known-place resolution already clamps), and a place-less follow-up
  ("why not the zone further north?") inheriting the prior turn's named place instead of
  falling back to the full demo region.
- `OrchestrationState.prior_intent` (new input field) and `POST /api/v1/query` now pass
  `session.last_intent` into it. The `query_understanding` node calls
  `resolve_reference()` after the LLM call, before location/persona/coordinates are
  derived from the result.
- "Offshore" is treated as due west — documented as a scoped simplification for this
  specific coastline (Mangaluru-Udupi runs roughly north-south), not a general
  onshore/offshore solver.

Tests: `tests/agents/query_understanding/test_reference.py` (7),
`tests/gis/test_distance.py`'s `offset_point_km` cases (5), and one full-stack API test
in `tests/api/test_query.py` proving a real two-turn `/query` conversation shifts the
resolved location deterministically and that the number in the result traces exactly to
`offset_point_km`'s own output — never to anything the LLM could have supplied itself.

## 3. Scenario Engine (architecture §32)

"MVP-lite: shares its implementation with multi-turn state — a scenario is simply a
perturbed re-entry into the same deterministic re-scoring path."

```
POST /api/v1/scenario {session_id, wave_height_delta_m?, wind_speed_delta_ms?}
        |
Load session.last_intent / last_weather_snapshot / last_marine_snapshot
        |
app.scenario.engine.run_scenario():
  1. Score the UNCHANGED baseline (RiskSuitabilityAgent.evaluate -> derive_safety_facts
     -> evaluate_safety_guard -> risk_inputs_for_decision -> make_decision)
  2. Copy weather/marine, apply the requested delta (floored at 0.0 — a physical bound,
     never a fabricated value), never mutating the caller's originals
  3. Score the perturbed copy through the SAME five functions
  4. Diff (risk_score_delta, decision_changed, safety_outcome_changed)
        |
ScenarioResult{label="SIMULATION — NOT LIVE DATA", baseline, scenario, ...}
```

No second risk/safety/decision formula exists for scenarios — `run_scenario` calls the
exact same functions the live orchestration pipeline uses. To make that possible without
duplicating logic, two small extractions were made from `app.orchestration.nodes`,
Refactorings, not new logic:

- `app.policy.safety_guard.derive_safety_facts(weather, marine, boundary_check,
  risk_suitability) -> SafetyFacts` (previously inlined in the `safety_guard` node).
- `app.decision.engine.risk_inputs_for_decision(risk_suitability) ->
  (risk_level, risk_score, confidence)` (previously inlined in the `decision` node).

Both are now called by both the live orchestration nodes AND the Scenario Engine —
verified behavior-identical by re-running the full orchestration suite unchanged after
each extraction.

`SessionState` gained `last_weather_snapshot`/`last_marine_snapshot` — the one
deliberate, documented exception to "session state never caches environmental
observations as still-current" (see `app.session.models`'s module docstring): they exist
solely as a scenario baseline, are never used to answer a live query, and every scenario
result built from them is always labeled `"SIMULATION — NOT LIVE DATA"`.

If no completed prior query exists for the session, `POST /api/v1/scenario` returns a
`422 SCENARIO_BASELINE_UNAVAILABLE` — never a guessed baseline.

Tests: `tests/scenario/test_engine.py` (7, including "baseline is never mutated" and "a
large enough perturbation flips the decision outcome"), `tests/api/test_scenario.py` (4,
including "scenario never overwrites the real session baseline").

## 4. Alert Engine (architecture §29)

"Mechanics: Hazard Detection -> Deduplication -> Severity-change check -> Send/Update
Alert. States: New, Updated, Escalated, Resolved."

`GET /api/v1/alerts?lat=&lon=` (defaults to the demo bbox centroid) computes hazards
on-demand from the same Weather/Oceanographic/GIS agents used elsewhere — this
architecture has no background scheduler/poller anywhere else, so this endpoint does not
introduce one either.

Five of architecture §29's seven named hazard rows are implemented, reusing existing
Risk Engine component functions with no second copy of the math
(`app.risk.components.wave_risk`/`wind_risk`/`restricted_zone_distance_risk`,
`app.risk.hazard_proxies.lightning_thunderstorm_proxy`,
`app.risk.engine.classify_risk_level`):

| Hazard | Status |
|---|---|
| High waves | Implemented — `wave_risk(wave_height) >= 0.5` |
| Strong wind | Implemented — `wind_risk(wind_speed) >= 0.5` |
| Thunderstorm/lightning proxy | Implemented — WMO 95-99, terminology-disciplined message citing DAMINI |
| Restricted-zone proximity | Implemented — `restricted_zone_distance_risk(distance_km) >= 0.5` |
| Risk-threshold crossing | Implemented — overall `RiskResult.level` in `{MODERATE, HIGH}` |
| Cyclone proxy | **Not implemented** — no pressure-tendency/gust/persistence signals are fetched by any agent in this codebase (same honest limitation `app.agents.common.risk_inputs` already documents for the Risk Engine itself) |
| Route entering a prohibited zone | **Not applicable to this endpoint** — only meaningful for an actual computed route, not a region snapshot |

Deduplication/state is provided by `app.alerts.store.AlertStore` (Redis-backed, same
graceful-degradation contract as `SessionStore`/`AgentCache`), keyed by a coarse
`round(lat, 2):round(lon, 2)` region key, storing the last-reported `{hazard_type:
severity}`. `app.alerts.engine.diff_alert_states` compares this call's detected hazards
against that state: unseen -> `New`; present before and crossing into a higher
`RiskLevel` band -> `Escalated`; present before with a materially different severity but
same band -> `Updated`; materially unchanged -> silently dropped (never re-reported);
present before but absent now -> `Resolved`, reported exactly once.

If the underlying weather/marine data could not be resolved, `AlertsResult.
data_unavailable=True` and the composite risk-threshold hazard is skipped — an empty
`alerts` list is never allowed to imply "checked and clear" when it actually means
"could not be checked" (per-hazard checks that only need the data that IS present still
run normally).

Tests: `tests/alerts/test_engine.py` (10, pure functions, no Redis/network),
`tests/api/test_alerts.py` (6, including a full New -> sustained-dedup -> Resolved
lifecycle across three real HTTP calls, and the "failed data never fabricates an
all-clear" case).

## 5. Standalone provenance retrieval (architecture §34)

`GET /api/v1/query/{query_id}/provenance`. `SessionStore` already keeps the MOST RECENT
provenance per *session*; `app.provenance.store.ProvenanceStore` (same Redis pattern)
additionally keeps one entry per *query_id*, written by `POST /api/v1/query` right after
the session write. A `query_id` with no matching entry returns `404
PROVENANCE_NOT_FOUND` — never reconstructed or guessed.

Tests: `tests/api/test_provenance.py` (3), including "provenance survives the session
moving on to a later turn."

## 6. Route comparison — deliberately not built

architecture §41 classifies "alternate route options" as SHOULD and "multi-route ranked
alternates" as STRETCH, explicitly below every MUST-HAVE item, with the rule "no stretch
work begins before every MUST-HAVE item is demoable end-to-end." `RouteRequest`
(`app.routing.models`) has no "candidate variant" concept, and the single-route A*
implementation computes exactly one optimal path per origin/destination — there is no
k-shortest-paths or ranked-alternates algorithm anywhere in this codebase to reuse.

Building a new multi-route ranking algorithm now would be new deterministic routing R&D
that neither this task's Rule 1 (architecture frozen) nor Rule 4 (no fabrication) permit
introducing casually. The existing `POST /api/v1/route` endpoint already fully supports
comparison as-is: a client can call it multiple times (different destinations, different
`requested_time`s) and compare the returned `RouteResult.metrics`/`feasibility_status`
directly — no new backend endpoint is needed for that pattern, so none was added. This
is a deliberate scope decision, not an oversight.

## 7. Mandatory safety-scenario regression suite

`tests/safety/test_mandatory_safety_scenarios.py` — an explicit, auditable proof of the
four required properties, composed entirely from existing building blocks (no new
deterministic logic):

1. HIGH risk + an LLM configured to claim "safe" -> the explanation never contains an
   unsafe affirmation (falls back to the deterministic template) and
   `provenance.decision.outcome`/`risk_level` are untouched — both as a direct unit test
   of `EvidenceExplanationAgent` and as a full `/api/v1/query` round trip with severe
   weather/marine values and a lying `FakeLLMProvider`.
2. INFEASIBLE route + a hypothetical "feasible" claim -> `RouteResult.feasibility_status`
   is a `Literal["FEASIBLE"]` field that structurally rejects any other value (Pydantic
   `ValidationError`), and `/api/v1/route` against a geofence-blocked destination returns
   a controlled `422 BLOCKED_LAND_OR_GEOFENCE` with `data: null` — no LLM is ever
   involved in `/route` at all.
3. Failed weather/marine data -> `safety.outcome == "BLOCK_MISSING_DATA"`,
   `decision.outcome == "NO_SAFE_RECOMMENDATION"`, and `evidence == []` (no fabricated
   numbers for data that was never resolved).
4. Unrecognized location -> `ClarificationNeeded`, never a guessed coordinate; a `/route`
   request missing `destination` entirely is rejected by Pydantic validation before any
   routing logic runs.

## 8. Full regression

`pytest -q` (excluding the four pre-existing infrastructure tests that require a live
local Postgres/Redis, unrelated to this phase): **499 passed** (up from Phase 5's 446),
zero regressions across the entire suite after every refactor and addition in this
phase.

## 9. Known limitations (honest, not hidden)

- Cyclone proxy is not computed anywhere in this codebase (Alert Engine included) — no
  agent fetches the pressure-tendency/gust/persistence signals `app.risk.hazard_proxies.
  cyclone_proxy` requires. This was already true before Phase 10 and remains true after
  it; the Alert Engine simply does not claim a hazard type it cannot honestly detect.
- Route comparison was deliberately not built (§6) — the existing single-route endpoint
  already supports the comparison pattern via repeated calls.
- The Scenario Engine's perturbation surface is limited to `wave_height_delta_m`/
  `wind_speed_delta_ms` — architecture §32's own example. Extending it to other risk
  factors (e.g. a hypothetical geofence change) is future work, not attempted here.
- "Offshore" in multi-turn reference resolution is hardcoded as due-west, correct for
  this demo coastline's orientation, not a general solution.
