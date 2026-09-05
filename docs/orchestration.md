# Phase 5 — LangGraph Orchestration

This document describes what is actually implemented for Phase 5. See
[`docs/architecture.md`](architecture.md) §10-§12, §21-§31, §34, §38 for the frozen
architecture this implements against, and [`docs/data_agents.md`](data_agents.md) for
the Phase 4 data agents this phase wires into a graph without reimplementing.

## 1. Purpose

Phase 5 adds the LangGraph orchestration layer that ties every previous phase together
into one conversational entrypoint (`POST /api/v1/query`): a typed graph that resolves
natural-language queries into structured intent, fans out to the three Phase 4 data
agents, evaluates risk/suitability/safety/decision through Phase 2's unmodified
deterministic engines, optionally attempts routing, and produces a grounded natural-
language explanation. It also adds the LLM Provider Abstraction Layer and the two
remaining architecture-named agents that actually call an LLM: Query Understanding and
Evidence & Explanation. **LangGraph is the only orchestration framework used — no
CrewAI, AutoGen, or LangChain agent-executor.**

## 2. Graph architecture

```
START
  |
  v
query_understanding  (LLM: RawIntentResult -> deterministic location/time resolution)
  |
  +-- clarification needed --------------------------------------------> END
  |
  '-- continue -> [weather, oceanographic, gis]   (parallel fan-out)
                          |
                          v
                  risk_suitability   (fan-in: waits for all three branches)
                          |
                          v
                   safety_guard      (Phase 2, unchanged)
                          |
                          v
                     decision        (Phase 2, unchanged)
                    /          \
        requires_route            (default)
       & safety == PASS               |
              |                       |
              v                       |
            route                    |
              \                      /
               '------> evidence <--'
                          |
                          v
                         END
```

Every path that reaches `evidence` or `route` passes through `safety_guard` and
`decision` first — this is enforced by the graph's edge topology itself (see
`app.orchestration.graph`), not by a runtime check the LLM could be tricked into
skipping. `tests/orchestration/test_graph_topology.py` asserts this structurally.

## 3. State (`app.orchestration.state.OrchestrationState`)

A typed Pydantic `BaseModel`, not a raw dict (Phase 5 task spec §16). Fields written by
more than one node in the same parallel step (`agent_runs`, `errors`) are declared
`Annotated[list[...], operator.add]` so LangGraph merges each branch's contribution
instead of raising `InvalidUpdateError` — confirmed via a live smoke test against the
installed `langgraph==1.2.11` package before being relied on. Every other field is
written by exactly one node and is a plain field.

Key fields: `query`, `session_id`, `now`, `language`, `persona`, `intent`,
`clarification`, `latitude`/`longitude` (the resolved query location's centroid),
`weather`/`marine` (Phase 1's `AgentResult`), `boundary_check`/
`nearest_hard_geofence_distance_km` (GIS), `risk_suitability` (Phase 2 wrapper),
`safety` (`SafetyGuardResult`), `decision` (`Decision`), `route`/`route_note`,
`provenance` (`DecisionProvenanceGraph`), `explanation` (`ExplanationResult`),
`agent_runs` (`list[AgentRunRecord]`), `errors`, `status`.

`app.orchestration.graph.build_orchestration_graph()`'s `.invoke()` returns a plain
dict (a LangGraph characteristic, not a bug); callers re-validate it via
`OrchestrationState.model_validate(...)` for typed access, exactly as confirmed in the
pre-implementation smoke tests.

## 4. Nodes (`app.orchestration.nodes.OrchestrationNodes`)

One class holding injected agent instances (constructor-injectable for tests), with one
method per graph node. Every node wraps exactly one existing agent/engine — **zero new
formulas, zero duplicated logic** (Phase 5 task spec §40):

| Node | Wraps |
|---|---|
| `query_understanding` | `app.agents.query_understanding.agent.QueryUnderstandingAgent` |
| `weather` | `app.agents.weather.agent.WeatherIntelligenceAgent` (Phase 4, unchanged) |
| `oceanographic` | `app.agents.oceanographic.agent.OceanographicIntelligenceAgent` (Phase 4, unchanged) |
| `gis` | `app.agents.gis.agent.GISGeofencingAgent` (Phase 4, unchanged) |
| `risk_suitability` | `app.agents.risk_suitability.agent.RiskSuitabilityAgent` |
| `safety_guard` | `app.policy.safety_guard.evaluate_safety_guard` (Phase 2, unchanged) |
| `decision` | `app.decision.engine.make_decision` (Phase 2, unchanged) |
| `route` | Documented deferral — see §14 |
| `evidence` | `app.agents.evidence_explanation.agent.EvidenceExplanationAgent` |

Each of `weather`/`oceanographic`/`gis` wraps its call in `try/except
InvalidCoordinateError` and converts a failure into `state.errors` + a `failed`
`AgentRunRecord` — the field itself stays `None`, which `safety_guard`'s
`has_critical_missing_data` check is specifically designed to catch downstream, never a
node deciding safety consequences on its own (architecture-level separation of
concerns, Phase 5 task spec §17).

## 5. Edges (`app.orchestration.edges`)

Two decider functions. `after_query_understanding` returns either the single string
`"clarify"` (mapped to `END`) or the list `["weather", "oceanographic", "gis"]`
(fanning out to all three in parallel — a decider returning a list of node names was
confirmed, via smoke test, to fan out correctly before being relied on).
`after_decision` returns `"route"` only when `intent.requires_route` **and**
`safety.outcome == "PASS"`, else `"evidence"` — routing is never attempted for a query
the Safety Guard has already blocked (fail-closed applied to routing too).

## 6. Agent contracts reused unchanged

`AgentResult`, `Evidence`, `SafetyGuardResult`, `Decision`, `RiskResult`,
`SuitabilityResult` — all verbatim from Phases 1-2, imported, never redefined. The new
`ConflictObject` contract (architecture §12/§20) is added to
`app.models.contracts` this phase but is structurally present only — every
`conflicts` list built by this phase is honestly empty (only one source exists per
domain; there is nothing to arbitrate yet).

## 7. LLM Provider Abstraction Layer (`app.llm`)

```
Agent code (Query Understanding / Evidence & Explanation)
        v
app.llm.factory.get_llm_provider(settings)   <- the ONLY place that imports a
        v                                       specific vendor adapter by name
Concrete LLMProvider  (claude.py | gemini.py | grok.py | fake.py)
```

`LLMProvider` (`app.llm.base`) is an ABC with exactly architecture §11a's contract:
`generate_structured(schema, system_prompt, user_prompt) -> BaseModel`,
`detect_language(text) -> str`. Selection is driven entirely by the `LLM_PROVIDER`
environment variable — agent code never imports `claude`/`gemini`/`grok` directly, and
swapping providers never touches agent code. **Claude is not mandatory** — it is one of
three equally-weighted optional adapters, all implemented via raw `httpx` calls (no
vendor SDK dependency): Claude via forced tool-use, Gemini via
`responseMimeType=application/json` + `responseSchema`, Grok via OpenAI-compatible
`response_format={"type":"json_object"}`. `retry_once_with_backoff`
(`app.llm.provider`) implements architecture §38's "retry once w/ backoff" uniformly
across all three; a configuration error (missing API key) is never retried.

## 8. Supported providers and what was actually verified

| Provider | Implementation | Live-tested? |
|---|---|---|
| `fake` | `FakeLLMProvider` — in-memory, deterministic, records every call | Yes — powers the entire default test suite |
| `claude` | Anthropic Messages API, forced tool-use | **No** — no `LLM_API_KEY` configured in this environment. Verified via `respx`-mocked HTTP tests only (`tests/llm/test_claude.py`) — request/response wiring, not real API behavior. |
| `gemini` | Google Generative Language API, JSON mode | **No** — same limitation, same mocked-only verification (`tests/llm/test_gemini.py`) |
| `grok` | xAI OpenAI-compatible chat completions | **No** — same limitation (`tests/llm/test_grok.py`) |

This is an honest limitation, not an oversight: no LLM API key exists in this
environment. `get_llm_provider()` fails closed with `LLMConfigurationError` when
`LLM_PROVIDER` is unset (the default) — the graph cannot silently run with a
half-configured LLM.

## 9. Query Understanding Agent

`app.agents.query_understanding.agent.QueryUnderstandingAgent`. One of only two agents
permitted to call an LLM. Its LLM-facing schema, `RawIntentResult`
(`app.agents.query_understanding.models`), **structurally cannot express a coordinate
or an absolute timestamp** — it has only `location_name`/`time_description` free-text
fields. `location.py`/`time_resolution.py` deterministically resolve those into the
architecture §12 `IntentResult.location`/`time_window` — the LLM's own words are never
copied into a geometry or a timestamp. An unrecognized place name, an unsupported
language, an LLM failure, or an empty query all return a structured
`ClarificationNeeded`, never a guess.

## 10. Risk & Suitability Agent

`app.agents.risk_suitability.agent.RiskSuitabilityAgent` — a thin wrapper. Every number
traces to Phase 2's unmodified `compute_risk`/`evaluate_suitability` and the exact
frozen weights (wave 0.25, wind 0.15, advisory/hazard 0.20, lightning proxy 0.10,
restricted-zone distance 0.15, coast distance 0.10, data-confidence-penalty 0.05).
`tests/agents/risk_suitability/test_agent.py` proves this by independently recomputing
the same score via the same Phase 2 call and asserting equality — not merely inspecting
the code. Missing/unusable weather or marine data returns
`status="insufficient_data"`, deliberately **not** a worst-case numeric substitute (that
policy belongs to Phase 4's routing provider only, which has a different constraint —
A* cannot leave a cell's cost undefined). The Safety Guard, not this agent, is what
turns "insufficient data" into a blocking outcome.

## 11. Evidence & Explanation Agent

`app.agents.evidence_explanation.agent.EvidenceExplanationAgent` — the second and only
other LLM-calling agent. Grounded **only** in a `DecisionProvenanceGraph` snapshot
serialized into the system prompt (see §12) — the LLM has no tool access, no internet
access, and no ability to call any deterministic engine. Two independent post-
generation checks (`app.agents.evidence_explanation.grounding`) gate every output:

1. `check_grounding` — every numeric token in the text must be within tolerance of a
   value actually present in the evidence (risk score/factors, suitability
   score/signal, route distance/cost, decision risk score/confidence).
2. `check_no_false_safety_claim` — if `decision.outcome == "NO_SAFE_RECOMMENDATION"`,
   the text must not contain an affirming-safety phrase ("is safe", "safe to", "go
   ahead", etc.).

A failing output is regenerated once (with a corrective instruction appended to the
system prompt), then falls back to `build_templated_explanation()`
(`app.agents.evidence_explanation.template`) — a fully deterministic, English-only
template that reads every number directly from the provenance object. This mechanism
is architecture §12 mechanism #5, implemented, not merely documented.

## 12. Decision Provenance Graph (`app.provenance.models.DecisionProvenanceGraph`)

The single object architecture §27 specifies is rendered identically by chat, the
Evidence Panel, and the Provenance view. Built once per query, in the `evidence` node,
from the final `OrchestrationState` — `RiskProvenance`, `SuitabilityProvenance`,
`GeographicProvenance`, `RouteProvenance` (only if a route was attempted),
`conflicts: list[ConflictObject]` (always empty this phase — see §6), `safety`,
`decision`. `AgentRunRecord` (one per node, in `state.agent_runs`) is a separate,
lighter *operational* trace ("which nodes ran, with what status/timing/source-tier"),
not a competing provenance system.

## 13. Session state (`app.session`)

`SessionState` (`app.session.models`) remembers **conversational** context only: the
last query, last detected language, last `IntentResult`, last `Decision`, last
`DecisionProvenanceGraph`. `SessionStore` (`app.session.store`) persists it to Redis
using the identical graceful-degradation contract as Phase 4's `AgentCache` — a Redis
outage or a corrupted entry is always treated as "no session," never a crash.

**Critically, environmental observations are never cached as session state.** Every new
turn re-invokes the Weather/Oceanographic agents fresh — which themselves re-run the
Temporal Validity Gate every time (Phase 1, unchanged) — so a follow-up query in the
same session can never present stale weather/marine data as still current merely
because a prior turn already fetched it (Phase 5 task spec §24).

## 14. Route conditionality — documented deferral, not a stub bug

`intent.requires_route` triggers the `route` graph node (via the conditional edge in
§5), proving the orchestration-integration wiring exists. The node itself, however,
does **not** invoke `app.routing.engine.calculate_route` this phase: that function
requires an explicit origin **and** destination coordinate pair
(`RouteRequest`/`Coordinate`), and `QueryUnderstandingAgent`/`IntentResult` only ever
resolve a single target location from a conversational query — there is no vessel-
location concept anywhere in this codebase to source an origin from, and inventing one
would violate the project's hard "never invent coordinates" rule (Phase 5 task spec
§11). The node instead returns a structured, honest `route_note` explaining this and
pointing to the already-functioning `POST /api/v1/route` endpoint (Phase 3), which
still requires and accepts explicit origin/destination coordinates directly. **No
second routing algorithm was built.** Extending Query Understanding to extract or
accept an origin is left for a later phase.

## 15. Language handling

`app.i18n.languages` — `SUPPORTED_LANGUAGES = {"en", "hi", "kn"}` (English, Hindi,
Kannada — architecture §30's MVP set). Deliberately minimal: this module is a
supported-language set and a display-name lookup, not a translation framework.
**Machine-readable outcomes (`RiskLevel`, `SafetyGuardOutcome`, `DecisionOutcome`)
are never translated** — they remain their exact English enum values everywhere in
state, the API response, and provenance. Only the Evidence & Explanation Agent's prose
is language-aware (the LLM is asked to respond in the detected language). The
deterministic templated fallback (§11) is **English-only** — there is no deterministic
translation mechanism without the LLM itself. This is an honest, documented limitation:
a template-fallback explanation for a Hindi/Kannada query is still English prose,
never mistranslated or silently dropped.

## 16. Deterministic safety boundary — how the LLM is prevented from ever influencing it

1. **Structural**: the graph topology (§2) puts `safety_guard` and `decision` on every
   path to `evidence`/`route`; there is no edge that bypasses them.
2. **Data-flow**: `SafetyFacts`/`make_decision`'s inputs come entirely from
   `state.boundary_check`, `state.risk_suitability`, `state.safety` — none of which the
   LLM ever writes to. The LLM (Query Understanding) only ever populates
   `state.intent`/`state.language`/`state.persona`, none of which the Safety Guard or
   Decision Engine reads.
3. **Post-hoc**: even the Evidence & Explanation Agent — which DOES see the final
   decision — cannot make its prose contradict it: `check_no_false_safety_claim`
   rejects any generated text claiming safety when the decision is
   `NO_SAFE_RECOMMENDATION`, falling back to the template.

`tests/orchestration/test_graph_flow.py::test_llm_cannot_make_the_decision_engine_recommend_a_blocked_query`
exercises all three layers together: a hostile fake LLM response claiming safety for a
geofence-blocked location still yields `NO_SAFE_RECOMMENDATION` and a rejected/
template-fallback explanation.

## 17. Error handling

Every node function returns normally on an *expected*, documented exception (an
invalid coordinate from a data agent — see §4) — never lets it propagate silently past
the Safety Guard. `app.orchestration.errors` provides `ok_run_record`/
`failed_run_record`/`degraded_run_record`/`skipped_run_record` so every node's outcome
is uniformly represented in `state.agent_runs`. A genuinely unexpected exception (a
programming error) is **not** caught — it propagates and fails the request loudly,
matching LangGraph's own default behavior (confirmed via smoke test: node exceptions
are not silently swallowed by the runtime).

## 18. Provenance / traceability

Every node appends exactly one `AgentRunRecord` (`agent_name`, `status`,
`started_at`/`finished_at`, `source_tier` where applicable, `confidence` where
applicable, `errors`) to `state.agent_runs` — a complete, ordered (modulo the parallel
branch's own non-determinism) operational trace of the whole request, independent of
the substantive `DecisionProvenanceGraph` (§12).

## 19. API — `POST /api/v1/query`

`app.api.v1.query`. Request: `{"query": str, "session_id": str | None}`. Response
follows architecture §34's envelope: `{data, evidence, confidence, provenance, errors,
session_id, query_id}`. `data.status` is `"completed"` or `"clarification_needed"`;
`data.decision`/`data.safety` are the raw machine-readable outcomes (§15); `evidence`
is the flattened `Evidence` list from the Weather/Oceanographic `AgentResult`s;
`provenance` is the full `DecisionProvenanceGraph`. `get_orchestration_nodes`/
`get_session_store` are FastAPI dependencies, overridable in tests with fast, offline
fakes — the same pattern Phase 4's `/route` endpoint established.

## 20. Testing

Categories A-J from the Phase 5 task spec, all using `FakeLLMProvider` — **zero
network/API-key dependency in the default suite**:

| Category | Location |
|---|---|
| A. LLM Provider | `tests/llm/` (`test_fake.py`, `test_factory.py`, `test_provider.py`, `test_claude.py`, `test_gemini.py`, `test_grok.py`) |
| B. Query Understanding | `tests/agents/query_understanding/` |
| C. LangGraph structure/flow | `tests/orchestration/test_graph_topology.py`, `test_graph_flow.py` |
| D. Risk/Suitability | `tests/agents/risk_suitability/test_agent.py` |
| E. Safety Guard (via orchestration) | `tests/orchestration/test_graph_flow.py` (boundary/missing-data blocking, LLM-cannot-bypass) |
| F. Decision Engine (via orchestration) | `tests/orchestration/test_graph_flow.py` |
| G. Explanation grounding | `tests/agents/evidence_explanation/` |
| H. Session | `tests/session/test_store.py`, `tests/api/test_query.py` (session continuity) |
| I. API | `tests/api/test_query.py` |
| J. Full regression | `pytest -m "not integration and not live"` — 446 passed (see §Performance/regression below) |

`tests/routing/test_api_route.py`'s land-fixture/open-water fixtures are reused by
name in `tests/orchestration/conftest.py` so orchestration tests exercise the SAME
geofence data Phase 3 already validated, not a second copy.

## 21. Configuration

New Phase 5 settings (`app.config.Settings`, `.env.example`): `LLM_PROVIDER`,
`LLM_MODEL`, `LLM_API_KEY` (placeholders since Phase 0, first actually consumed this
phase), `SESSION_TTL_SECONDS` (default 3600). No new required configuration — the
graph runs with `LLM_PROVIDER` unset only if a `FakeLLMProvider`/real provider is
explicitly injected (as every test does); the real `/api/v1/query` endpoint requires
`LLM_PROVIDER` to be configured to a real value (fails closed with
`LLMConfigurationError` otherwise, surfaced as a 500 — deliberately not silently
degraded, since a half-configured LLM layer is a deployment error, not a runtime
condition to route around).

## 22. Demo/live behavior

`ORCA_MODE` continues to govern Weather/Oceanographic/GIS fallback exactly as Phase 4
built it (LIVE→CACHED→STATIC/DEMO, STATIC only under `ORCA_MODE=demo`) — orchestration
adds no new mode semantics. A full end-to-end smoke run in this development
environment (real Open-Meteo HTTP calls, `FakeLLMProvider` for both LLM-calling
agents) was run manually and produced correct `RECOMMEND`/`BLOCK_BOUNDARY`/route-
conditional outcomes — see the Phase 5 final report for the actual transcripts.

## 23. Known limitations (honest, not hidden)

- **No real LLM provider was live-tested** (§8) — no API key available in this
  environment. Wiring is verified via mocked HTTP tests only.
- **Route computation from a conversational query is deferred** (§14) — no origin
  concept exists yet; `POST /api/v1/route` remains the only way to compute an actual
  route this phase.
- **No official-advisory ingestion exists** — `has_active_high_severity_advisory` is
  always `False` in the Safety Guard's inputs (an honest "never checked," not a
  fabricated "no hazard" claim) — same limitation Phase 4/5's shared
  `build_normalized_risk_components` already documents for `advisory_or_hazard_risk`.
- **No alternative-site search exists** — `alternative_exists` is always `False` when
  calling `make_decision`, so a `HIGH`-risk query with no blocking Safety Guard outcome
  always resolves to `NO_SAFE_RECOMMENDATION`, never `PROVIDE_ALTERNATIVES`, in this
  phase's actual runtime behavior (the code path exists in Phase 2's Decision Engine,
  unreachable from orchestration until a candidate-site search is built).
- **Evidence Arbitration / Conflict Resolution (architecture §19-20) is not
  implemented** — `conflicts` is always an empty list; only one source exists per
  domain (Open-Meteo), so there is nothing to arbitrate.
- **The templated explanation fallback is English-only** — no deterministic
  translation exists without the LLM (§15).
- **`nearest_hard_geofence_distance_km` is reused for both "restricted zone distance"
  and "coast distance"** — a Phase 4-established simplification
  (`app.agents.common.risk_inputs`), continued unchanged, not introduced this phase.
