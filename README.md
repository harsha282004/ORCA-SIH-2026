# ORCA — Marine EcOsystem Reasoning with Collaborative Agents

**SIH26176 | Sponsor: ISRO | Theme: Disaster Management**

ORCA is a conversational, agentic marine-intelligence platform that fuses satellite-derived,
oceanographic, meteorological, and geospatial data through collaborative specialized agents,
reasons across space and time under a deterministic safety and evidence layer, and produces
explainable, provenance-traceable recommendations in the user's own language.

The full, frozen architecture is the single source of truth for this implementation:
[`docs/architecture.md`](docs/architecture.md).

> **Core principle:** AI interprets and explains → deterministic code computes and enforces
> safety → evidence supports every claim → the human makes the final decision.

---

## Current status: Phase 4 — Data Agents

This repository currently implements **Phase 0 (Infrastructure)** through **Phase 4
(Data Agents)** of the development roadmap (architecture §44). **No LLM calls and no
LangGraph exist yet** — the three Phase 4 agents are deterministic service components
(architecture §10's own table marks none of them as an LLM call), fully testable with
zero real network access via mocked HTTP and a fake Redis double.

**Implemented in Phase 0:** FastAPI + PostgreSQL/PostGIS + Redis + React/TS/Tailwind
infrastructure, Docker Compose, real health/readiness checks.

**Implemented in Phase 1:** Live Open-Meteo Weather + Marine adapters, the
`NormalizedObservation`/`Evidence` data contracts, unit/CRS/timestamp normalization, the
Temporal Validity Gate, the Marine Data Fabric, and PostGIS storage for observations. Full
detail: [`docs/data_pipeline.md`](docs/data_pipeline.md).

**Implemented in Phase 2:**
- Deterministic GIS: polygon validation with explicit (never silent) repair, Haversine +
  point-to-polygon distance, hard/soft geofence classification, a deterministic candidate
  grid (`backend/app/gis/`)
- The Risk Engine, with weights and thresholds matching architecture §22 exactly
  (verified byte-for-byte against its own worked example), fail-fast weight validation,
  and explicit missing-data handling (`backend/app/risk/`)
- Confidence, computed separately from risk and never folded into it
  (`backend/app/reasoning/confidence.py`)
- The Fishing Suitability Engine, structurally distinct from and never overriding the
  official PFZ (`backend/app/suitability/`)
- The Policy & Safety Guard and Decision Engine, matching architecture's exact typed
  contracts and outcome sets (`backend/app/policy/`, `backend/app/decision/`)
- Lightning/cyclone hazard **proxies** — explicitly labeled as proxies, never claiming
  authoritative detection or tracking (`backend/app/risk/hazard_proxies.py`)
- 219 tests total (212 offline, unconditionally reproducible)

Full detail: [`docs/deterministic_core.md`](docs/deterministic_core.md).

**Implemented in Phase 3:**
- A deterministic risk-aware A* routing engine (`backend/app/routing/`) — Haversine
  heuristic and grid generation reused directly from Phase 2's `app.gis`, edge cost
  reusing Phase 2's Risk Engine components, no second GIS/risk implementation
- Land and hard-geofence masking at the grid-cell level (reusing Phase 2's geofence hard
  categories — land is not a separate rule), with corner-cutting explicitly prevented
- Origin and destination validated before A* ever runs, always — coordinate range,
  routing-domain bounds, hard-geofence/land block, cell-level navigability
- A structured `NO_ROUTE_FOUND` error when no path exists — never a partial or
  best-effort route
- Reuses Phase 1's Temporal Validity Gate and Phase 2's confidence policy as a
  routing-refusal gate — stale/expired/missing data or low confidence blocks routing
  before any grid work happens
- `POST /api/v1/route` — real HTTP endpoint, demo-fixture-backed, clearly labeled
  `data_quality="fixture"` in every response, never presented as live
- 270 tests total (263 offline, unconditionally reproducible)

Full detail: [`docs/routing.md`](docs/routing.md).

**Implemented in Phase 4:**
- Weather Intelligence, Oceanographic Intelligence, and GIS & Geofencing Agents
  (`backend/app/agents/`) — architecture §10's exact three non-LLM data-agent roles,
  each wrapping its Phase 1/2/3 primitives unchanged (no reimplemented Open-Meteo
  parsing, no second geometry/Haversine implementation)
- A real 3-tier LIVE → CACHED → STATIC/DEMO fallback per agent (architecture §16),
  Redis-backed caching with deterministic keys, and DEMO-mode-only synthetic fallback —
  LIVE mode never silently substitutes synthetic data (architecture §16a)
- `POST /api/v1/route` now backed by real (bounded, sampled) live environmental data
  instead of Phase 3's flat fixture — verified end-to-end via a real HTTP call
  (~12.5s, correct varying per-cell risk scores); Phase 3's A*/cost/grid code is
  completely unmodified
- 347 tests total (340 offline, unconditionally reproducible)

Full detail: [`docs/data_agents.md`](docs/data_agents.md).

**Explicitly NOT implemented yet** (belongs to later phases):
LLM calls of any kind, LangGraph orchestration, the Query Understanding / Risk &
Suitability / Evidence & Explanation / Route agents, the Decision Provenance Graph, the
Alert Engine, the Scenario Engine, and the full map/visualization interface. Static GIS
datasets (coastline, bathymetry, protected areas, EEZ) have not been acquired yet — the
`DEMO_BBOX` they'd be clipped to is still a proposal pending confirmation, so every
geofence used remains a labeled fixture, not real data. `routes`/`route_segments`
persistence (architecture §33) remains deliberately unimplemented — see `docs/routing.md`
§13 for why. The corresponding backend directories for later-phase components (`llm/`,
`orchestration/`, `provenance/`, `alerts/`, `scenario/`, `i18n/`, `session/`) exist (per
the architecture's frozen repository structure, §42) but are intentionally empty.

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- Git

For running backend/frontend outside Docker during development:
- Python 3.12+
- Node.js 20+

---

## How to run (Docker Compose — recommended)

From the repository root, in PowerShell:

```powershell
# 1. Create your local environment file (never commit this)
Copy-Item .env.example .env

# 2. Build and start every service
docker compose up --build
```

This starts:

| Service    | URL                              |
|------------|-----------------------------------|
| Frontend   | http://localhost:3000             |
| Backend    | http://localhost:8000             |
| PostgreSQL | localhost:5432                    |
| Redis      | localhost:6379                    |

Verify:

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/health/ready
```

## How to stop

```powershell
docker compose down
```

To also remove the PostgreSQL volume (destroys all data):

```powershell
docker compose down -v
```

---

## Health endpoints

| Endpoint | Purpose | Depends on external services? |
|---|---|---|
| `GET /health` | Liveness — process is up | No |
| `GET /api/v1/health/ready` | Readiness — real PostgreSQL, PostGIS, and Redis checks | Yes |

`GET /api/v1/health/ready` returns HTTP 200 with `"status": "ready"` only when every
dependency is actually healthy; otherwise it returns HTTP 503 with `"status": "not_ready"`
and per-dependency detail so a failure is never silently reported as success.

---

## Development setup (without Docker)

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Point at your own PostgreSQL/Redis instances, e.g. via a backend/.env file:
#   POSTGRES_HOST=localhost
#   REDIS_HOST=localhost
uvicorn app.main:app --reload --port 8000
```

Run tests:

```powershell
# Offline unit tests only (no network, no infrastructure)
pytest -m "not integration and not live"

# Live tests — real calls to Open-Meteo (network required, no database needed)
pytest -m live

# Integration tests — requires live PostgreSQL/PostGIS/Redis (e.g. via docker compose)
pytest -m integration
```

Run the Phase 1 ingestion pipeline against live data and print a validation report
(from the repository root):

```powershell
python scripts/ingest_demo_observations.py

# Also write the results into PostGIS (requires a reachable database):
python scripts/ingest_demo_observations.py --write-db

# Also seed the static-layer provenance registry (requires a reachable database):
python scripts/ingest_demo_observations.py --register-static-sources
```

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Opens at http://localhost:3000 (or the port Vite reports). Set `VITE_API_BASE_URL` in
`frontend/.env` if the backend is not on `http://localhost:8000`.

---

## Environment configuration

See [`.env.example`](.env.example) for the full list of recognized variables. Never
commit a real `.env` file — it is gitignored. `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY`
remain configuration placeholders only; no LLM provider is called yet (architecture
§11a, §23 "LLM ≠ Safety Authority"). `DEMO_BBOX_*` is a **proposed** value — see
[`docs/demo_region.md`](docs/demo_region.md).

---

## Repository structure

Matches the architecture's frozen repository structure (§42). See
[`docs/architecture.md`](docs/architecture.md) for the authoritative version.
`backend/app/data/`, `backend/app/fabric/`, `backend/app/models/` (Phase 1),
`backend/app/gis/`, `backend/app/risk/`, `backend/app/reasoning/`,
`backend/app/suitability/`, `backend/app/policy/`, `backend/app/decision/` (Phase 2),
`backend/app/routing/` (Phase 3), and `backend/app/agents/` (Phase 4) are now
implemented. Directories still empty (`llm/`, `orchestration/`, `provenance/`,
`alerts/`, `i18n/`, `session/`, `scenario/`) are reserved for later phases and contain
only a `.gitkeep`.

---

## Future phases

Development proceeds strictly in order, with validation between each phase
(architecture §44):

1. ~~**Phase 0 — Infrastructure**~~ (complete)
2. ~~**Phase 1 — Data foundation**~~ (static GIS acquisition remains pending `DEMO_BBOX`
   confirmation, see `docs/demo_region.md`)
3. ~~**Phase 2 — Deterministic core**~~ (Risk Engine, GIS, Safety Guard, Decision Engine;
   see `docs/deterministic_core.md`)
4. ~~**Phase 3 — Routing**~~ (risk-aware A*, origin/destination validation gates, hard
   geofence blocking, "no route found" structured error; see `docs/routing.md`)
5. ~~**Phase 4 — Data agents**~~ (this repository's current state — Weather/
   Oceanographic/GIS agents, Redis caching, 3-tier fallback, real agent-backed routing;
   see `docs/data_agents.md`)
6. **Phase 5 — LangGraph orchestration**: full agent graph, LLM Provider Abstraction
   Layer, language detection, multi-turn session state
7. **Phase 6 — Evidence, provenance, explanation**: Decision Provenance Graph, grounding
   checks, localized explanation generation
8. **Phase 7 — Frontend/map**: risk heatmap, evidence/provenance panels, Agent Activity
   panel
9. **Phase 8 — Fallback, testing, demo hardening**

No phase begins before the previous one is validated. This repository does not implement
Phase 5 or later — that is deliberate.
