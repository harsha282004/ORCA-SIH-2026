# Phase 11 — Full Integration, QA, Reliability & Demo Hardening

This document describes what was actually found and fixed for Phase 11. See
[`docs/architecture.md`](architecture.md) for the frozen architecture, and
[`docs/orchestration.md`](orchestration.md) / [`docs/phase_10.md`](phase_10.md) for the
systems this phase audited and hardened without redesigning.

Phase 11 is QA/hardening only — no new agents, databases, routing engines, or
orchestration frameworks were introduced. Three genuine, reproducible defects were found
through REAL testing (a running backend, a running frontend, live external APIs, a real
browser) rather than the offline unit-test suite alone — the offline suite's dependency
overrides had structurally never exercised the code paths where these defects lived.

## 1. Infrastructure

Docker Desktop and WSL are both not installed in this development environment, so the
project's intended `docker-compose`-based Postgres/PostGIS/Redis path could not be
exercised. A native PostgreSQL 18 Windows service is present but has no PostGIS
extension available (none is bundled for PG18 on Windows here) and its superuser
credentials were not available to provision the `orca` role. No Redis installation exists
on this machine (no Docker, no WSL, no native/portable binary found). The user was asked
how to proceed and chose to leave this as a documented environment limitation rather than
have this session modify system-level Postgres authentication or install new local
infrastructure. The 4 tests that require these services
(`tests/test_infrastructure.py::test_database_connectivity`,
`::test_postgis_available`, `::test_redis_connectivity`,
`tests/test_pipeline_e2e.py::test_pipeline_through_postgis_write`) remain failing in
*this* environment for that reason — confirmed environment-only, not a code defect: the
same suite passes 100% otherwise, and `GET /api/v1/health/ready` correctly and honestly
reports `"not_ready"` with real per-dependency error detail when these dependencies are
absent (verified against a live running server), rather than fabricating a healthy status.

## 2. Real defects found and fixed

### 2a. Opaque, unstructured 500 when the LLM provider is unconfigured

`POST /api/v1/query`'s `get_orchestration_nodes` dependency constructs
`QueryUnderstandingAgent`/`EvidenceExplanationAgent`, which resolve an `LLMProvider` via
`app.llm.factory.get_llm_provider` — this raises `LLMConfigurationError` when
`LLM_PROVIDER` is unset (this repository's own `.env.example` default). Because this
happens during FastAPI dependency resolution, before the route handler body runs, it
previously propagated all the way to Starlette's default exception handler: a bare
`500 "Internal Server Error"` with no JSON body, indistinguishable from a genuine crash to
any caller and unusable by the frontend's error handling. Verified against a real running
`uvicorn` instance (not just the always-overridden test suite).

**Fix:** `get_orchestration_nodes` (`backend/app/api/v1/query.py`) now catches
`LLMConfigurationError` and raises a `fastapi.HTTPException(503, detail={"code":
"LLM_NOT_CONFIGURED", "message": ...})` — still fails closed (architecture.md §38: a
half-configured LLM layer is a deployment error, never silently routed around), just with
a structured, parseable body instead of an opaque one. No stack trace was ever leaked
either way (confirmed via a raw `curl -i` before the fix — Starlette's non-debug default
handler already suppressed it).

Regression test: `tests/api/test_query_llm_not_configured.py` (deliberately does not
override the dependency, to exercise the real construction path).

### 2b. Open-Meteo Marine's own rate limit under routing's concurrent sample fetch

`POST /api/v1/route` computes a bounded `4×4=16`-point environmental sample grid via
`AgentBackedEnvironmentalProvider.prepare()`, fetching Weather+Oceanographic data for all
16 points concurrently (`ThreadPoolExecutor(max_workers=16)`, architecture Phase 4 task
spec §33). Repeated live testing (direct calls to the real agents, then the real
`/api/v1/route` endpoint through a running server) reproduced intermittent failures: some
fraction of the 16 marine-API calls returned `HTTP 429 {"reason":"Too many concurrent
requests"}`. The underlying `SourceAdapterError` was then silently discarded (`except
SourceAdapterError: pass`, contradicting that exception class's own docstring, "Never
silently swallowed"), the affected sample site degraded to the synthetic/DEMO fallback
tier with a `MISSING_TIMESTAMP` temporal-validity status, and — correctly, per the
Temporal Validity Gate — the *entire* route computation was refused with `422
MISSING_DATA`, even though a live answer was available moments later. This was initially
misdiagnosed as a timeout issue (raising `HTTP_TIMEOUT_SECONDS` reduced but did not
eliminate it); instrumenting the previously-silent failure path revealed the true cause
(HTTP 429), at which point timeout tuning was reverted as unnecessary and the real fix
applied instead.

**Fix:**
- `app.agents.common.fallback.fetch_with_fallback` now wraps the live fetch+parse step in
  `app.llm.provider.retry_once_with_backoff` — the SAME retry-once-with-backoff primitive
  architecture.md §38 already specifies as a general policy and that this codebase
  already used for LLM provider calls, reused here rather than reimplemented.
- The underlying failure reason is no longer discarded: it is threaded into
  `AllSourcesUnavailableError`'s message and, in DEMO mode, into the degraded
  `AgentResult.warnings` text, so a future investigation does not require live debugging
  to see *why* a fallback occurred.

Verified via 3 repeated live runs against the real endpoint after the fix: 0 failures
(previously ~50% of runs degraded). `HTTP_TIMEOUT_SECONDS` remains at architecture.md
§11b's original 6s default — unchanged, since it was not the actual cause.

Regression tests: `tests/agents/common/test_fallback.py::test_transient_rate_limit_is_retried_once_and_succeeds`,
`::test_persistent_rate_limit_still_falls_back_and_reports_the_reason`.

### 2c. CORS rejected any frontend dev server not on the exact default port

`Settings.cors_origins` only ever listed `http://localhost:3000` and
`http://localhost:5173`. In practice, `vite`/`vite preview` silently falls back to the
next free port whenever the default is already taken (reproduced live: a stale dev server
occupying ports 3000-3005 pushed a fresh one to 3006) — every subsequent backend call was
then blocked by the browser's own CORS enforcement, and the frontend's generic
network-error handling (`postJson`'s `catch` block) surfaced this as *"ORCA's backend is
not reachable right now"* — a misleading message for what was actually a CORS policy
rejection, not a network outage. Reproduced against both `POST /api/v1/route` (Route
Planner) and `POST /api/v1/query` (Ask ORCA) via a real headless-browser session, and
confirmed via the browser's own console error
(`Access to fetch ... has been blocked by CORS policy`).

**Fix:** `app.main`'s `CORSMiddleware` now also sets `allow_origin_regex=
r"http://localhost:\d+"` — additive to (not a replacement of) the existing
`allow_origins` list. This project has no multi-tenant/production CORS requirement
(architecture.md has none); permitting any `localhost` port is the standard, safe pattern
for a local-only development/demo backend and does not widen access beyond the
developer's own machine — verified with a regression test that a non-localhost origin is
still correctly rejected.

Verified via a full real-browser round trip after the fix: Route Planner returns a
genuine `FEASIBLE` result with real live distance/confidence/risk data rendered in the
UI; Ask ORCA correctly reaches the backend and shows its real (LLM-not-configured)
response instead of the misleading network-error message.

Regression tests: `tests/test_cors.py` (3 tests: default port allowed, an arbitrary
fallback port allowed, a non-localhost origin still rejected).

## 3. Real end-to-end verification performed

Beyond the offline `pytest` suite, this phase ran a live backend (`uvicorn`), a live
frontend (`vite`/`vite preview`), and a headless real browser (Microsoft Edge via
`puppeteer-core`) to exercise:

- `GET /health`, `GET /api/v1/health/ready` (both dependency-down and confirmed-honest
  reporting), `POST /api/v1/query` (empty query, unconfigured-LLM path), `POST
  /api/v1/route` (real live Open-Meteo data, `FEASIBLE` result), `GET /api/v1/alerts`
  (real live data, a genuine "wave" hazard detected and reported), `POST /api/v1/scenario`
  and `GET /api/v1/query/{id}/provenance` (both controlled-404 and happy-path, via
  `curl`).
- The cinematic hero: confirmed `clip1.mp4`/`clip2.mp4` are the only video sources present
  in the rendered DOM, `final.mp4` and any MotionSites/CloudFront remote video are absent,
  neither clip has `autoplay` or `loop`, forward scroll genuinely advances `currentTime`,
  backward scroll genuinely reverses it, and no console errors occur during scroll
  interaction.
- Responsive layout at 375×812, 820×1180, 1280×800, and 1400×900 — no horizontal overflow
  at any of the four.
- `prefers-reduced-motion` — the page loads and renders normally under it.
- Ask ORCA — confirmed it calls the real `POST /api/v1/query` (no mock response path
  exists in the UI code at all — verified by reading `frontend/src/lib/api.ts`), renders
  the user's message and ORCA's real response/limitation state.
- Route Planner — confirmed it calls the real `POST /api/v1/route` and renders the actual
  returned feasibility/distance/confidence/risk fields, not placeholder values.
- Status page — confirmed it calls the real `GET /api/v1/health/ready` and renders actual
  per-dependency status text.

## 4. Security audit

No secrets or credentials found in the repository (tracked or newly added this phase);
`.env`/`.env.*` remain gitignored, `.env.example` contains placeholders only. No new
endpoint added this phase leaks a stack trace or internal path — all return structured
`{code, message}` bodies (including the new 503 from finding 2a). Frontend dependency
tree remains minimal (`react`, `react-dom`, `react-router-dom`, `lucide-react`) with no
suspicious or drift-introducing packages. No `console.log`/`print` of sensitive data
found in either codebase.

## 5. Architecture drift check

Grepped the entire repository (backend, frontend, docs) for CrewAI, LangChain, ChromaDB,
Ollama, Llama, Next.js, Three.js, GSAP, Framer Motion, Lenis, and Locomotive Scroll —
every hit found is a code comment or doc sentence explicitly confirming their ABSENCE
(e.g. "no vector store, no LangChain, no Ollama"), never an actual usage. `final.mp4` and
MotionSites/CloudFront are referenced only in a code comment confirming they are not
used; `frontend/public/videos/` contains exactly `clip1.mp4` and `clip2.mp4`, nothing
else. No drift found.

## 6. Documentation corrected

`README.md` still described the repository as being at "Phase 5" and listed the Alert
Engine, Scenario Engine, and cinematic frontend as future/not-yet-implemented — all
three were already built (Phase 6/10). Corrected: the "Current status" section, the
per-phase implementation list, the repository-structure paragraph (`alerts/`/`scenario/`
were described as empty placeholders; they are not), and the phase roadmap (renamed
"Future phases" to "Development history" since there is no unimplemented phase left
before Phase 12/deployment).
