"""ORCA backend entrypoint.

Phase 5 adds the LangGraph orchestration entrypoint (`POST /api/v1/query`)
alongside Phase 3's deterministic routing endpoint. Both remain thin HTTP
wrappers — no business logic lives in this module.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.alerts import router as alerts_v1_router
from app.api.v1.fishing import router as fishing_v1_router
from app.api.v1.health import router as health_v1_router
from app.api.v1.layers import router as layers_v1_router
from app.api.v1.safety import router as safety_v1_router
from app.api.v1.query import router as query_v1_router
from app.api.v1.route import router as route_v1_router
from app.api.v1.scenario import router as scenario_v1_router
from app.api.v1.voice import router as voice_v1_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ORCA Backend",
    description="Marine EcOsystem Reasoning with Collaborative Agents — API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Phase 11 QA finding: `cors_origins` only ever listed the two literal
    # default Vite ports (3000/5173). In practice `vite`/`vite preview` auto-
    # increments to the next free port whenever the default is already
    # taken (reproduced live: a stale dev server on 3000 pushed a fresh one
    # to 3006) — the frontend then silently fails every backend call with a
    # misleading "backend is not reachable" message, when the real cause is
    # CORS, not reachability. This is a local-development-only project
    # (architecture.md has no multi-tenant/production CORS requirement);
    # permitting any localhost port is the standard, safe pattern for this
    # case — it does not widen access beyond the developer's own machine.
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_v1_router, prefix="/api/v1")
app.include_router(route_v1_router, prefix="/api/v1")
app.include_router(query_v1_router, prefix="/api/v1")
app.include_router(scenario_v1_router, prefix="/api/v1")
app.include_router(alerts_v1_router, prefix="/api/v1")
app.include_router(layers_v1_router, prefix="/api/v1")
app.include_router(fishing_v1_router, prefix="/api/v1")
app.include_router(safety_v1_router, prefix="/api/v1")
app.include_router(voice_v1_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    """Liveness check. Deliberately independent of any external dependency."""
    return {"status": "ok", "service": "orca-backend"}
