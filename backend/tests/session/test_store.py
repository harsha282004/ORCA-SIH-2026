"""Session persistence — architecture.md §31. Reuses the same
graceful-degradation contract as `app.agents.common.cache.AgentCache`.
"""
from __future__ import annotations

import redis
import pytest

from app.session.models import SessionState
from app.session.store import SessionStore


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self.store[key] = value
        return True


class BrokenRedis:
    def get(self, key: str):
        raise redis.ConnectionError("simulated outage")

    def set(self, key: str, value: str, ex: int | None = None):
        raise redis.ConnectionError("simulated outage")


def test_get_returns_none_when_no_client_configured() -> None:
    store = SessionStore(None, ttl_seconds=60)
    assert store.get("some-id") is None


def test_save_then_get_round_trips() -> None:
    client = FakeRedis()
    store = SessionStore(client, ttl_seconds=60)
    session = SessionState(session_id="abc", last_query="hello", last_language="hi")
    store.save(session)

    fetched = store.get("abc")
    assert fetched is not None
    assert fetched.last_query == "hello"
    assert fetched.last_language == "hi"


def test_get_returns_none_for_unknown_session_id() -> None:
    store = SessionStore(FakeRedis(), ttl_seconds=60)
    assert store.get("does-not-exist") is None


def test_corrupted_entry_is_treated_as_a_miss_not_a_crash() -> None:
    client = FakeRedis()
    client.store["orca:session:abc"] = "not valid json{{{"
    store = SessionStore(client, ttl_seconds=60)
    assert store.get("abc") is None


def test_redis_outage_on_get_is_a_miss_not_a_crash() -> None:
    store = SessionStore(BrokenRedis(), ttl_seconds=60)
    assert store.get("abc") is None


def test_redis_outage_on_save_never_raises() -> None:
    store = SessionStore(BrokenRedis(), ttl_seconds=60)
    store.save(SessionState(session_id="abc"))  # must not raise


def test_get_or_create_with_no_session_id_creates_a_new_session() -> None:
    store = SessionStore(FakeRedis(), ttl_seconds=60)
    session = store.get_or_create(None)
    assert session.session_id
    assert session.turn_count == 0


def test_get_or_create_with_unknown_session_id_creates_a_session_with_that_id() -> None:
    store = SessionStore(FakeRedis(), ttl_seconds=60)
    session = store.get_or_create("my-explicit-id")
    assert session.session_id == "my-explicit-id"


def test_get_or_create_with_known_session_id_returns_the_existing_session() -> None:
    client = FakeRedis()
    store = SessionStore(client, ttl_seconds=60)
    original = SessionState(session_id="abc", turn_count=3)
    store.save(original)

    fetched = store.get_or_create("abc")
    assert fetched.turn_count == 3
