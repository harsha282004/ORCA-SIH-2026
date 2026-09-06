"""Redis-backed alert-state persistence — architecture.md §29's
"Deduplication" step needs to remember the last-reported severity per
hazard per region between calls. Mirrors `app.session.store.SessionStore`'s
exact graceful-degradation contract (a Redis outage or corrupted entry is
always a cache MISS — an empty prior state — never a crash); no new caching
technology is introduced.
"""
from __future__ import annotations

import json

import redis

_KEY_PREFIX = "orca:alerts:"


def _key(region_key: str) -> str:
    return f"{_KEY_PREFIX}{region_key}"


class AlertStore:
    def __init__(self, client: "redis.Redis | None" = None, *, ttl_seconds: int):
        self._client = client
        self.ttl_seconds = ttl_seconds

    def get(self, region_key: str) -> dict[str, float]:
        if self._client is None:
            return {}
        try:
            raw = self._client.get(_key(region_key))
        except redis.RedisError:
            return {}
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
            return {str(k): float(v) for k, v in data.items()}
        except (ValueError, TypeError, AttributeError):
            return {}  # a corrupted entry is treated as no prior state, never a crash

    def save(self, region_key: str, state: dict[str, float]) -> None:
        if self._client is None:
            return
        try:
            self._client.set(_key(region_key), json.dumps(state), ex=self.ttl_seconds)
        except redis.RedisError:
            return  # persistence is best-effort; a failed write must never fail the request
