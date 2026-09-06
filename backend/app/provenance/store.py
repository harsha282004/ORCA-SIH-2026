"""Redis-backed provenance persistence, keyed by `query_id` — architecture.md
§34's `GET /query/{id}/provenance` ("Decision Provenance Graph object
standalone"). `SessionStore` already keeps the MOST RECENT provenance per
*session*; this store additionally keeps one entry per *query_id* so a
specific past turn's provenance can be retrieved on its own, independent of
whatever the session has moved on to since.

Mirrors `app.session.store.SessionStore`'s exact graceful-degradation
contract (a Redis outage or corrupted entry is always a cache MISS, never a
crash) — no new caching technology is introduced.
"""
from __future__ import annotations

import redis

from app.provenance.models import DecisionProvenanceGraph

_KEY_PREFIX = "orca:provenance:"


def _key(query_id: str) -> str:
    return f"{_KEY_PREFIX}{query_id}"


class ProvenanceStore:
    def __init__(self, client: "redis.Redis | None" = None, *, ttl_seconds: int):
        self._client = client
        self.ttl_seconds = ttl_seconds

    def get(self, query_id: str) -> DecisionProvenanceGraph | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(_key(query_id))
        except redis.RedisError:
            return None
        if raw is None:
            return None
        try:
            return DecisionProvenanceGraph.model_validate_json(raw)
        except ValueError:
            return None  # a corrupted entry is treated as not found, never a crash

    def save(self, provenance: DecisionProvenanceGraph) -> None:
        if self._client is None:
            return
        try:
            self._client.set(_key(provenance.query_id), provenance.model_dump_json(), ex=self.ttl_seconds)
        except redis.RedisError:
            return  # persistence is best-effort; a failed write must never fail the request
