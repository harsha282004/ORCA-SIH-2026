"""Redis connectivity check used by the readiness endpoint.

Phase 0 scope only: verify the backend can reach Redis and get a PONG back.
No caching architecture, session storage, or alert storage is implemented
here — that belongs to later phases.
"""
import redis

from app.config import get_settings

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def check_redis() -> dict:
    try:
        healthy = bool(get_client().ping())
        return {"status": "healthy" if healthy else "unhealthy"}
    except Exception as exc:  # noqa: BLE001 — connectivity probe, report any failure
        return {"status": "unhealthy", "error": str(exc)}
