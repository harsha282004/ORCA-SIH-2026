"""Redis-backed cache for Data Agent results — architecture.md §16's
CACHED tier. Reuses the project's existing Redis client
(``app.services.cache``); no new caching technology is introduced.

Cache keys are fully deterministic — namespace + quantized location + an
hourly time bucket — never a random UUID (Phase 4 task spec §35). A
corrupted entry or a Redis outage is always treated as a cache MISS, never
a crash: caching is best-effort, and a data agent must degrade gracefully
(fall through to the next tier) rather than take the whole request down.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import redis

from app.models.contracts import NormalizedObservation


def build_cache_key(*, namespace: str, latitude: float, longitude: float, time_bucket: str, grid_precision: int = 3) -> str:
    """`orca:agent:<namespace>:<lat>:<lon>:<time_bucket>`.

    Coordinates are rounded to `grid_precision` decimal places (3 decimals
    ~= 111m) so nearby requests within the same neighborhood share one
    cache entry instead of every floating-point centroid producing a
    guaranteed miss.
    """
    lat_q = round(latitude, grid_precision)
    lon_q = round(longitude, grid_precision)
    return f"orca:agent:{namespace}:{lat_q}:{lon_q}:{time_bucket}"


def time_bucket_hourly(at_time: datetime) -> str:
    """Quantizes a timestamp to the hour — matches Open-Meteo's own hourly
    cadence (Phase 1's ``app.data.open_meteo_common.HOURLY_STEP``), so one
    cache entry naturally covers exactly one forecast step.
    """
    utc = at_time.astimezone(timezone.utc) if at_time.tzinfo else at_time.replace(tzinfo=timezone.utc)
    return utc.strftime("%Y%m%dT%H")


class AgentCache:
    """Thin, swappable wrapper — tests inject a fake/mock client (or a
    real ``fakeredis``-style instance) so the whole agent test suite never
    requires a live Redis instance (Phase 4 task spec §9).
    """

    def __init__(self, client: "redis.Redis | None" = None, *, ttl_seconds: int):
        self._client = client
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> list[NormalizedObservation] | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except redis.RedisError:
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return [NormalizedObservation.model_validate(o) for o in payload]
        except (ValueError, TypeError):
            return None  # a corrupted cache entry is a miss, never a crash

    def set(self, key: str, observations: list[NormalizedObservation]) -> None:
        if self._client is None or not observations:
            return
        try:
            payload = json.dumps([o.model_dump(mode="json") for o in observations])
            self._client.set(key, payload, ex=self.ttl_seconds)
        except redis.RedisError:
            return  # caching is best-effort; a failed write must never fail the request

    def get_json(self, key: str) -> dict | list | None:
        """Generic JSON cache read, for agent metadata that isn't a
        NormalizedObservation batch (e.g. the GIS agent's static-dataset
        status). Same graceful-degradation contract as `get()`.
        """
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except redis.RedisError:
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def set_json(self, key: str, value: dict | list) -> None:
        if self._client is None:
            return
        try:
            self._client.set(key, json.dumps(value), ex=self.ttl_seconds)
        except redis.RedisError:
            return
