# Phase 6 — Multilingual & Conversational Intelligence Report

**Status:** Complete. English, Hindi, and Kannada are live-verified end-to-end (real Groq calls, real browser). Automatic deterministic language detection now cross-checks the LLM. Conversational follow-up reuse (route alternatives/comparison, fishing comparison, "explain") is implemented and unit-tested; one real gap in LLM follow-up *classification* reliability was found live and is disclosed, not hidden. 641 backend tests pass (30 new), same 2 pre-existing failures as the Phase 5 baseline. Frontend typecheck/lint/build are clean.

---

## 1. Executive Summary

Phase 6 did **not** need to build multilingual support from nothing: Phase 1–5 already had `SUPPORTED_LANGUAGES = {en, hi, kn}`, a single combined LLM call that extracts both intent and language, a grounding-checked Evidence Agent that already accepts a `language` parameter, and a `reference_type`/`reference_delta` mechanism for follow-ups. This phase's real work was (1) auditing that existing machinery honestly, (2) adding the deterministic script-detection cross-check the task explicitly asked for, (3) closing two real gaps a genuine live conversation surfaced — a native-script gazetteer miss and an English-only safety-claim blocklist — and (4) building the conversational follow-up reuse layer (`operation`/`selection_reference`, compact session-stored route/fishing summaries) that did not exist before.

## 2. Existing Conversational Architecture (Audit Findings)

- **`app.session.models.SessionState`** already existed (Phase 5): `last_query`, `last_language`, `last_intent`, `last_decision`, `last_provenance`, plus two Scenario-Engine-only environmental snapshots explicitly documented as "never treated as still-current." Redis-backed (`app.session.store.SessionStore`), same TTL/graceful-degradation contract as every other cache in the project.
- **`app.agents.query_understanding.reference.resolve_reference`** already existed (Phase 5): a genuine deterministic reference-resolution boundary — the LLM only ever names *what kind* of reference this is (`refers_to_prior`, `reference_type`, `reference_delta.offshore_distance_km`); all actual geometry (an offshore offset, inheriting a prior named place) is computed here, never by the LLM.
- **`LLMProvider.detect_language()`** exists on every adapter (Groq, Gemini, Claude, Grok, Fake) as part of the frozen `architecture.md §11a` interface — but is **dead code**: nothing in `app/agents/` calls it. The language actually used comes from `RawIntentResult.language`, extracted by the SAME single Groq call that classifies intent — already free, no second round-trip.
- **`EvidenceExplanationAgent`** already had almost everything task §20–23 asks for: a `language`/`persona` parameter, a post-generation grounding check (`is_grounded_and_safe`: every numeric token must trace to real evidence, and a `NO_SAFE_RECOMMENDATION` decision can never be affirmed as safe), one retry, then a deterministic template fallback — exactly task §23's "LLM failure must not become computation failure."
- **`app.i18n.languages`** already existed: `SUPPORTED_LANGUAGES = {en, hi, kn}`, `DEFAULT_LANGUAGE = "en"` — this phase's own priority list, already chosen in an earlier phase.

**Conclusion:** the multilingual/conversational *skeleton* was already real and correctly designed; Phase 6's job was to make automatic language detection more reliable, close two real script/language gaps, and build the missing follow-up-reuse layer on top of the existing session mechanism.

## 3. Existing Language Detection

Confirmed via `grep -rn detect_language`: implemented on every LLM adapter, tested in `tests/llm/test_fake.py`, **never called** by any agent. This is the exact situation task §6 describes ("if existing LLM-based detection exists: evaluate its reliability and cost") — its cost would be a full second LLM round-trip per turn purely for language ID, which the task explicitly says to avoid (§6, §24). Left unused, as found; not deleted (it is part of the frozen provider interface contract).

## 4. Supported Languages

| Language | Detection | Query Understanding | Response | Tested | Status |
|---|---|---|---|---|---|
| English | Deterministic (Latin-script + closed-class signal words) + LLM | Yes (existing) | Yes | Live, real Groq, real browser | **Supported** |
| Hindi | Deterministic (Devanagari Unicode block) + LLM | Yes (existing) | Yes | Live, real Groq, real browser (Scenario 3, §20) | **Supported** |
| Kannada | Deterministic (Kannada Unicode block) + LLM | Yes (existing) | Yes | Live, real Groq, real browser (Scenario 2, §20) | **Supported** |
| Tamil | Deterministic script detection implemented (`app/i18n/detect.py`) | Not attempted — `SUPPORTED_LANGUAGES` unchanged | — | Script detection unit-tested only; NOT sent to Groq/tested end-to-end | **Not supported — untested, not claimed** |
| Telugu | Deterministic script detection implemented | Not attempted | — | Script detection unit-tested only | **Not supported — untested, not claimed** |
| Malayalam | Deterministic script detection implemented | Not attempted | — | Script detection unit-tested only | **Not supported — untested, not claimed** |

Per task §4's own instruction ("do NOT claim support for a language unless it is actually tested"): Tamil/Telugu/Malayalam get **script detection only** (a real, tested, reusable building block for a future phase) — `SUPPORTED_LANGUAGES` was deliberately left unchanged at `{en, hi, kn}`, so a Tamil/Telugu/Malayalam query still correctly resolves to a graceful, honest `ClarificationNeeded` ("ORCA currently supports English, Hindi, and Kannada"), never a fabricated claim of support.

## 5. Language Detection Method — Exact Implementation

`app/i18n/detect.py::detect_script_language(text) -> str | None` — a single pass over the query string counting characters by Unicode script block (Kannada `U+0C80–U+0CFF`, Devanagari `U+0900–U+097F`, Tamil `U+0B80–U+0BFF`, Telugu `U+0C00–U+0C7F`, Malayalam `U+0D00–U+0D7F`). No network call, no model, microsecond-scale.

- If an Indic script strictly dominates any Latin content, that script's code wins (script identification for these five is essentially unambiguous — a real Kannada sentence cannot be mistaken for Hindi).
- If Latin content is at least as large AND the text contains at least one of ~30 closed-class English function/marine-domain words ("the," "near," "safe," "fishing," "tomorrow," ...), returns `"en"`.
- Otherwise returns `None` — **deferring to the LLM's own answer**, deliberately. Pure script matching can prove "this text contains Kannada characters" but can never prove "this Latin-script text is English rather than French/German/Spanish" (same alphabet) — confidently guessing `"en"` for arbitrary Latin text would silently override a CORRECT LLM answer with a wrong one, live-verified to matter: `test_french_text_is_not_misclassified_as_english` exists specifically because an earlier, cruder version of this function did exactly that.

**Wired in** (`app.agents.query_understanding.agent.QueryUnderstandingAgent.understand`): immediately after the single Groq call returns `RawIntentResult`, if `detect_script_language(query)` returns a non-`None` result different from what the LLM said, the LLM's `language` field is overridden. **Never a second LLM call** — a pure cross-check on the one call already being made.

## 6. Query Normalization

Unchanged, pre-existing design, confirmed still correct: `RawIntentResult` (LLM-facing — free text `location_name`/`destination_name`/`time_description`, no coordinate/timestamp field at all) vs. `IntentResult` (deterministically resolved `location`/`destination`/`time_window` dicts). The original user query string is never discarded — it flows through as `OrchestrationState.query` and is what the Evidence Agent's grounding check and any conversational context ultimately trace back to.

## 7. Conversational Context

Two new orthogonal fields, added to `RawIntentResult`/`IntentResult` (never a new intent class, per task §10/§30):

- `operation: "evaluate" | "compare" | None` — "compare" for "which is safer?"/"which is safest?".
- `selection_reference: "primary" | "alternative" | None` — which previously-returned option a follow-up names.

`reference_type == "follow_up_explanation"` (Phase 5, unchanged) already covers "why?" — deliberately not duplicated as a third `operation` value.

**Real, live-caught reliability finding**: the very first live test of a Kannada "there" follow-up (`ಅಲ್ಲಿ ಅಲೆಗಳ ಪರಿಸ್ಥಿತಿ ಹೇಗಿದೆ?`) returned `refers_to_prior: False` from the LLM — the system prompt's only example of a follow-up cue was in English ("what about Friday?"). Fixed by adding explicit Hindi/Kannada follow-up-pattern examples to the same instruction (§10 below has the exact before/after). Re-verified: the SAME query now correctly returns `refers_to_prior: True`. This was a real gap, not a hypothetical one, and the fix is disclosed here rather than silently folded into "multilingual support implemented."

## 8. Session State

`SessionState` gained four new, deliberately compact fields (task §14's "do not store excessive conversation history" honored — no full route/candidate geometry, no message history beyond `last_query`):

- `last_selected_point: dict | None` — `{latitude, longitude, label, source}`, the exact point ORCA most recently discussed (a top fishing candidate, a route destination, a safety-check location) — more specific than `last_intent.location`'s whole named-place bbox.
- `last_fishing_candidates: list[dict] | None` — top-5 ranked candidates' compact summaries (label, lat/lon, risk/suitability/decision — no geometry).
- `last_route_options: list[dict] | None` — same idea for route + alternatives (label, endpoint, distance, risk, decision, safety — no path cells).
- `last_route_comparison: dict | None` — the `RouteComparisonResult` already computed by Phase 5's `compare_routes`, reused verbatim.

Reuses the existing Redis-backed `SessionStore` and its existing TTL — no new persistence mechanism, no schema migration (pydantic models with new optional fields deserialize old sessions fine — the four new fields simply default to `None`).

## 9. Context Resolution

`resolve_reference` gained one new optional parameter, `prior_selected_point` (from `SessionState.last_selected_point`, threaded through as `OrchestrationState.prior_selection`): when a follow-up names no new place, it now anchors to the exact previously-discussed POINT (falling back to the whole prior named-place bbox only if no such point exists — the exact pre-Phase-6 behavior, still tested and passing).

**A real bug found and fixed via live testing**: the code that updates `last_selected_point` after every turn originally ran unconditionally, including for a turn that resolved to the generic whole-region default (`location.type == "region"`) — such a turn is NOT more specific context than whatever was already remembered, but the original code clobbered the precise "Area A" anchor with the generic region centroid anyway. Caught live (a Kannada follow-up the LLM did not classify as `refers_to_prior` — see §7 — fell through to this code and overwrote the anchor, breaking the NEXT follow-up in the same conversation). Fixed: the update is now skipped whenever the current turn's own resolved location is the generic region default. Documented in the code itself, not just here.

## 10. Temporal Context

Unchanged and correctly reused: `app.agents.query_understanding.time_resolution.resolve_time_window` (pre-existing) resolves "today"/"tomorrow"/"tomorrow morning"/etc. deterministically against the real current time — the LLM only ever supplies free text, never an absolute timestamp. Per task §16's explicit instruction, the Phase 3 `requested_time`-ignored-by-single-value-agents bug was **not** touched; nothing in Phase 6 needed the hourly-time-series workaround, since no new temporal capability was added this phase.

## 11. Multilingual Fishing

Live-verified end-to-end, real Groq, real browser: a Kannada query ("ಮಂಗಳೂರಿನ ಹತ್ತಿರ ಮೀನುಗಾರಿಕೆಗೆ ಸೂಕ್ತವಾದ ಸ್ಥಳ ಹುಡುಕಿ") correctly classified as `zone_recommendation`, ran the SAME `app.fishing.engine.generate_candidates` every other language already uses, and returned a fully-Kannada Groq explanation citing the REAL risk score (0.136) with no numeric alteration. Same for Hindi. The "which is safest?" comparison-reuse path (§7's `operation=="compare"`) is unit-tested (7/7 passing, §20) but was **not** observed to trigger in one specific live English test — the terse follow-up "Which one is safest?" (with no re-mention of "fishing"/"area") was classified by the LLM as a fresh `safety_check` rather than `zone_recommendation`+`compare`. ORCA's behavior in that case was still correct and safe (a genuine fresh evaluation, not a crash or a wrong answer) — just not the reuse-optimized path. Disclosed as a real LLM-classification-reliability limitation in §23, not hidden.

## 12. Multilingual Safety

Live-verified: Hindi safety/fishing query ("मंगलुरु के पास सुरक्षित मछली पकड़ने की जगह खोजो") returned a fully-Hindi explanation with the exact real risk score (0.136) preserved. The Evidence Agent's grounding check (`app/agents/evidence_explanation/grounding.py`) was found to have an English-only false-safety-claim blocklist — a real gap for exactly this kind of Hindi/Kannada safety response — extended with the Hindi/Kannada equivalents of "is safe"/"you can proceed" (as multi-word phrases, deliberately NOT the bare stems, which would also match their own negation, e.g. "सुरक्षित नहीं" = "NOT safe"; see §15 for the exact phrases and reasoning). Lightning-unavailable phrasing (task §19) is unchanged, existing, language-neutral machinery (`app.hazard`'s `unavailable_sources`, Phase 4) — the Evidence Agent explains whatever real facts are in the provenance, in the requested language, and was not given new instructions this phase.

## 13. Multilingual Routing

Not separately live-tested in Phase 6 (a Kannada/Hindi *routing* query specifically) due to hitting the Groq daily token-rate-limit (§17) late in this session — but the mechanism is identical to fishing/safety: `QueryUnderstandingAgent` extracts `destination_name` (Phase 5) via the SAME single LLM call regardless of language, `OrchestrationNodes.route()` (Phase 5, unmodified this phase) runs the same deterministic `generate_route_alternatives`/`evaluate_route_safety`/`compare_routes`, and the Evidence Agent explains it in whatever language was detected — no language-specific branch exists anywhere in the routing path. This is a disclosed gap in THIS phase's live verification coverage, not a known defect (recorded honestly in §23 rather than silently claimed as tested).

## 14. Evidence Preservation

Unchanged, pre-existing, reused: `is_grounded_and_safe` traces every numeric token in the generated text back to a real evidence value (0.05 tolerance for rounding). Live-verified across three languages that a real risk score (0.136 / 0.223 / 0.22, depending on the exact query) survives localization exactly — never altered, never a "60.22 → 62.2" type corruption task §8 warns against. The `reused_prior_result` flag (new, Phase 6) additionally discloses to the frontend when a response was answered from stored context rather than a fresh evaluation — evidence provenance about the ANSWER's own freshness, not just its numbers.

## 15. Groq Integration

Prompt structure unchanged (task §21's "do not blindly increase prompt size" honored): the Evidence Agent's system prompt still receives exactly the same compact JSON facts object (decision/risk/suitability/safety/route/conflicts) it always did — Phase 6 added no new fields to this prompt. The Query Understanding system prompt gained ~180 words of multilingual follow-up examples (§7/§9) and the new `operation`/`selection_reference` field instructions — still one call, still returning one structured JSON object, never two round-trips.

`_UNSAFE_AFFIRMATION_PHRASES` (grounding.py) extended: `"सुरक्षित है"`, `"सुरक्षित हैं"`, `"जा सकते हैं"`, `"आगे बढ़ें"` (Hindi); `"ಸುರಕ್ಷಿತವಾಗಿದೆ"`, `"ಮೀನುಗಾರಿಕೆ ಮಾಡಬಹುದು"`, `"ಮುಂದುವರಿಸಬಹುದು"` (Kannada) — deliberately multi-word (never the bare stems, which would also match their own negation) — unit-tested (6 new tests, §20) including a check that these phrases correctly do NOT trigger when the decision is not `NO_SAFE_RECOMMENDATION`.

## 16. LLM Failure Handling

Unchanged pre-existing mechanism, **live-verified under a REAL failure this session**: extensive live multilingual testing exhausted this deployment's Groq daily token budget (200,000 TPD). The next query (`POST /api/v1/query` with a route follow-up) returned, verbatim: *"could not understand the query: groq rate limit: {...} Limit 200000, Used 199412..."* as a structured `ClarificationNeeded` — never a raw 500, never a fabricated answer, never a crash. This is `architecture.md §38`'s pre-existing fail-closed design, exercised by a genuine production condition rather than a mock, and is exactly task §23/§42's requirement working as intended.

## 17. Rate Limit / Cost Behavior

No new LLM calls were added anywhere in Phase 6's own code — `detect_script_language` (§5) replaces zero calls with zero calls (it runs alongside the existing single call, not instead of a second one that never existed); `_handle_conversational_followup` (§7/§11) REPLACES a full deterministic re-computation with ONE Groq explanation call reusing stored data — the LLM call count per follow-up either stays the same (one explanation call) or, when `operation=="explain"`-style reuse applies, is unchanged from the non-conversational path. Rate-limit handling itself (`LLMRateLimitError` deliberately excluded from Groq's own retry-once policy — architecture's own documented choice, `app/llm/groq.py`, unmodified) was live-verified this session (§16) — no retry amplification occurred; the single 429 response was surfaced immediately as a clarification.

## 18. Ask ORCA UI

`frontend/src/components/app/AskOrca.tsx` — enhanced in place, same page (`/ask-orca`), no redesign:

- A language badge (EN / हिन्दी / ಕನ್ನಡ) on every ORCA turn, showing the response's actual language.
- A manual language selector (Auto / English / हिन्दी / ಕನ್ನಡ) — "Auto" (the default) sends no override at all; a manual choice sends `language_override` (§19).
- A "from earlier result" badge when `reused_prior_result` is true.
- A compact `ResultCard` (new) — reads `fishing_candidates.top`/`route`/`marine_safety` directly off the existing response `data` object (never computed in the component) to show the recommended area/route/safety level inline, evidence-preserving per task §20.
- Example queries now include one Kannada and one Hindi query, alongside the existing two English ones.

## 19. API Changes

`POST /api/v1/query` — additive only, no new endpoints (`/kannada-query` etc. were explicitly forbidden, task §34, and were never considered):

- Request gains `language_override: str | None` (task §32) — applied ONLY after the full deterministic pipeline has already run on `final_state`, changing nothing but which language the response/explanation is written in. Unsupported codes are silently ignored (fall back to detected language), never a crash.
- Response `data` gains `reused_prior_result: bool` (present only on a conversational-reuse response).

## 20. Testing

**Backend: 641 passed, 2 pre-existing failures** (up from Phase 5's 611/2 baseline — **30 new tests, zero new failures, the exact same 2 pre-existing failures by name**). Two additional `@pytest.mark.live` tests (INCOIS WMS, GEBCO WMS — real government servers, unrelated to Phase 6) flaked transiently during full-suite runs this session and passed cleanly on isolated re-run — confirmed external-service flakiness, not a regression, consistent with every prior phase's own experience with these same two live markers.

- `tests/i18n/test_detect.py` (10) — English/Kannada/Hindi/Tamil/Telugu/Malayalam detection, mixed-script dominance, digits/punctuation-only and empty-string → `None`, bare place name and French text correctly NOT misclassified as English.
- `tests/agents/evidence_explanation/test_grounding.py` (+6) — Hindi/Kannada false-safety-claim detection (both catching real violations and correctly passing legitimate non-blocked/negated text).
- `tests/agents/query_understanding/test_reference.py` (+3) — `prior_selected_point` precedence over the prior named place, demo-bbox clamping, backward-compatible no-op when omitted.
- `tests/api/test_query_followup.py` (7, new file) — `_handle_conversational_followup` unit tests: route-alternative reuse, route-compare reuse, fishing-compare reuse (including correctly excluding a lower-risk-but-BLOCKED candidate from the eligible pool), and three "returns None, falls through" cases.
- `tests/api/test_query.py` (+4) — Kannada response language end-to-end, language-override changes response language, language-override does NOT change the deterministic decision/safety outcome (task §41, directly verified), unsupported override is ignored not a crash.

**Frontend**: `npx tsc --noEmit` — 0 errors. `npm run lint` (ESLint) — 0 errors/warnings. `npm run build` — succeeds.

**E2E (live Puppeteer, headless Edge, real Groq, real browser, against the running Docker stack)**:
1. English: "Find a suitable fishing area near Mangaluru." → real recommendation, ResultCard shows Area/Suitability HIGH/Risk LOW/real coordinates, EN badge — **zero console errors**.
2. Kannada: "ಮಂಗಳೂರಿನ ಹತ್ತಿರ ಮೀನುಗಾರಿಕೆಗೆ ಸೂಕ್ತವಾದ ಸ್ಥಳ ಹುಡುಕಿ" → response contains Kannada script, ಕನ್ನಡ badge shown — **zero console errors**.
3. Hindi: "मंगलुरु के पास सुरक्षित मछली पकड़ने की जगह खोजो" → response contains Devanagari script — **zero console errors**, **zero direct external marine-provider calls from the browser** (network-monitored).
4. Manual override: an ENGLISH query with the language selector set to "ಕನ್ನಡ" → the response is written in Kannada despite the English input — proving the override changes ONLY the response language.
5. Cross-phase regression: `/safety`, `/marine-map` (hazard toggle), `/fishing`, `/route-planner` re-verified — all unaffected, **zero console errors**.
6. Real LLM-failure path exercised live (§16) via genuine Groq rate-limit exhaustion — structured clarification, no crash.

The "which is safest?" fishing-compare-reuse path (§11) and a live Kannada/Hindi routing query (§13) were NOT independently E2E-verified this session due to the rate-limit exhaustion in item 6 above — disclosed as a real coverage gap in §23, not silently omitted.

## 21. Performance

Measured live this session:
- Deterministic script detection: sub-millisecond (a single string pass), never separately timed because it is not a network call.
- Single-language conversational query (fishing/safety, English or Hindi/Kannada): 6-22s (dominated by the SAME live environmental sampling + Groq call every prior phase already measured — Phase 6 added no new latency source to this path beyond the one-time script-detection pass).
- Conversational follow-up reuse path (route alternative/compare, when it triggers): one Groq explanation call only, no deterministic re-computation — inherently faster than a fresh evaluation (not independently timed this session due to the rate-limit exhaustion, but structurally guaranteed by the code: no `generate_route_alternatives`/`generate_candidates` call exists on that path at all).
- The Groq daily token budget (200,000 TPD on this deployment's tier) was exhausted by this session's OWN extensive multi-language, multi-turn live testing — a real, disclosed operational constraint (§17), not a Phase 6 regression.

## 22. Security / Privacy

No API keys, credentials, or internal provider secrets appear in any response, log line, or session-stored field added this phase — verified by inspection of every new `SessionState`/response field (`last_selected_point`, `last_fishing_candidates`, `last_route_options`, `last_route_comparison`, `reused_prior_result`, `language_override`): all are either coordinates/labels already present in existing public API responses, or booleans/enums. `SessionState` continues to store only conversational context (never raw LLM prompts/responses, never the Groq API key, which lives solely in `Settings`/environment configuration and was never touched this phase).

## 23. Known Limitations

1. **Tamil/Telugu/Malayalam are NOT supported** — script detection exists and is tested, but `SUPPORTED_LANGUAGES` was deliberately left at `{en, hi, kn}` because end-to-end query understanding/response generation in these languages was never tested (task §4's own instruction).
2. **Follow-up classification reliability**: the LLM does not 100% consistently recognize a terse, context-only follow-up ("which one is safest?" with no re-mention of fishing) as `operation=="compare"` with the right `intent_class` — live-verified to sometimes fall through to a fresh (correct, but non-reused) evaluation instead. The underlying reuse mechanism itself is proven correct by 7/7 passing unit tests; the gap is specifically in LLM classification consistency for maximally-terse phrasing, not in the deterministic reuse code.
3. **Multilingual routing was not independently live-tested this session** (§13) — the mechanism is identical in design to fishing/safety (same single LLM call, same language-neutral deterministic engines), but a live Kannada/Hindi ROUTE query specifically was not observed end-to-end before the Groq rate limit was exhausted.
4. **Mixed-language (code-switched) input** (task §27) is handled only via the deterministic detector's dominant-script heuristic (§5) and the LLM's own general capability — no dedicated code-switch parser was built (task's own "do not over-engineer code-switching" instruction), and this was not separately live-tested this phase.
5. The false-safety-claim blocklist (§15) is, as documented in the code itself, a heuristic safety net, not complete NLP coverage — a genuinely novel Hindi/Kannada unsafe-affirmation phrasing outside the extended list could still slip through this ONE check (the deterministic Decision Engine's `NO_SAFE_RECOMMENDATION` outcome itself remains authoritative regardless).

## 24. Technical Debt

Per task §50, the following were **not** touched this phase (as instructed):
1. The Phase 3 `requested_time`-ignored-by-single-value-agents bug — unrelated to any Phase 6 change.
2. The Phase 1 Redis GIS-dataset-status cache-staleness issue — unrelated.
3. Phase 4's lightning-unavailable-does-not-force-UNKNOWN gap — unrelated; the Evidence Agent's own language-neutral phrasing of "unavailable" data is unchanged.
4. Phase 4's single-reference-point Marine Map hazard layer — unrelated.
5. Phase 5's lack of a dedicated temporal-routing UI — unrelated; no new temporal capability was added.

Item 6 (Phase 5's lack of route-specific conversational follow-ups) was **addressed** this phase — see §7/§9/§11/§13 for what was built and its live-verified/tested status, and §23 items 2/3 for what remains only partially verified.

New Phase 6 technical debt: the follow-up-classification reliability gap (§23 item 2) and the untested-live-routing-conversation gap (§23 item 3) are both recorded here as the honest carry-forward items for a future session, once Groq quota resets.

## 25. Phase 7 Readiness

Yes, conditionally. The conversational-context layer (`operation`/`selection_reference`, compact session-stored summaries, `_handle_conversational_followup`) is a clean, additive extension with no reverse dependencies — a future phase can extend it (e.g. resolving "the second option" to an explicit index, or adding hazard-specific follow-ups) without restructuring what exists. The two live-verification gaps in §23 (items 2 and 3) are the natural first things to re-verify once the Groq daily quota resets, not architectural blockers.
