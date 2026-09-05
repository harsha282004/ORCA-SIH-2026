"""PostgreSQL/PostGIS connectivity checks used by the readiness endpoint.

Phase 0 scope only: verify the backend can reach the database and that the
PostGIS extension is installed. No ORCA business tables are defined here.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def check_database() -> dict:
    """Verify basic connectivity to PostgreSQL via SELECT 1."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as exc:  # noqa: BLE001 — connectivity probe, report any failure
        return {"status": "unhealthy", "error": str(exc)}


def check_postgis() -> dict:
    """Verify the PostGIS extension is installed and report its version."""
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        return {"status": "healthy", "version": version}
    except Exception as exc:  # noqa: BLE001 — connectivity probe, report any failure
        return {"status": "unhealthy", "error": str(exc)}
