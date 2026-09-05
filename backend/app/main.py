"""ORCA backend entrypoint.

Phase 5 adds the LangGraph orchestration entrypoint (`POST /api/v1/query`)
alongside Phase 3's deterministic routing endpoint. Both remain thin HTTP
wrappers — no business logic lives in this module.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_v1_router
from app.api.v1.query import router as query_v1_router
from app.api.v1.route import router as route_v1_router
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_v1_router, prefix="/api/v1")
app.include_router(route_v1_router, prefix="/api/v1")
app.include_router(query_v1_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    """Liveness check. Deliberately independent of any external dependency."""
    return {"status": "ok", "service": "orca-backend"}
