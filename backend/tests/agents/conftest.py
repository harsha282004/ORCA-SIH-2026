"""Shared test doubles for the Phase 4 agent test suite — no real Redis,
no real network access anywhere in this package's offline tests.
"""
from __future__ import annotations

import redis
import pytest


class FakeRedis:
    """A minimal in-memory stand-in for redis.Redis — just get/set with
    TTL bookkeeping ignored (tests don't need real expiry timing).
    """

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self.store[key] = value
        return True


class BrokenRedis:
    """Simulates a Redis outage — every call raises redis.RedisError."""

    def get(self, key: str):
        raise redis.ConnectionError("simulated Redis outage")

    def set(self, key: str, value: str, ex: int | None = None):
        raise redis.ConnectionError("simulated Redis outage")


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def broken_redis() -> BrokenRedis:
    return BrokenRedis()
