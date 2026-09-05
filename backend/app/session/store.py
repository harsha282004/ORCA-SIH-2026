"""Redis-backed session persistence — reuses the same graceful-degradation
contract as `app.agents.common.cache.AgentCache` (a Redis outage or a
corrupted entry is always a cache MISS — i.e. a fresh session — never a
crash). No new caching technology is introduced.
"""
from __future__ import annotations

import json

import redis

from app.session.models import SessionState

_KEY_PREFIX = "orca:session:"


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


class SessionStore:
    def __init__(self, client: "redis.Redis | None" = None, *, ttl_seconds: int):
        self._client = client
        self.ttl_seconds = ttl_seconds

    def get(self, session_id: str) -> SessionState | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(_key(session_id))
        except redis.RedisError:
            return None
        if raw is None:
            return None
        try:
            return SessionState.model_validate(json.loads(raw))
        except (ValueError, TypeError):
            return None  # a corrupted session entry is treated as no session, never a crash

    def save(self, session: SessionState) -> None:
        if self._client is None:
            return
        try:
            self._client.set(_key(session.session_id), session.model_dump_json(), ex=self.ttl_seconds)
        except redis.RedisError:
            return  # persistence is best-effort; a failed write must never fail the request

    def get_or_create(self, session_id: str | None) -> SessionState:
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
            return SessionState(session_id=session_id)
        return SessionState()
