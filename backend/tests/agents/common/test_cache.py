from datetime import datetime, timezone

from app.agents.common.cache import AgentCache, build_cache_key, time_bucket_hourly
from app.models.contracts import NormalizedObservation, QualityMetadata

NOW = datetime(2026, 9, 5, 10, 30, tzinfo=timezone.utc)


def make_observation(parameter: str = "wave_height", value: float = 1.2) -> NormalizedObservation:
    return NormalizedObservation(
        source="test",
        source_type="forecast",
        source_tier="live",
        parameter=parameter,
        value=value,
        unit="m",
        latitude=12.9,
        longitude=74.8,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=NOW,
        is_forecast=True,
        retrieved_at=NOW,
        mode="demo",
        is_live=True,
        quality=QualityMetadata(),
    )


def test_cache_key_is_deterministic() -> None:
    key1 = build_cache_key(namespace="weather", latitude=12.9123, longitude=74.8123, time_bucket="20260905T10")
    key2 = build_cache_key(namespace="weather", latitude=12.9123, longitude=74.8123, time_bucket="20260905T10")
    assert key1 == key2


def test_cache_key_quantizes_nearby_coordinates_together() -> None:
    key1 = build_cache_key(namespace="weather", latitude=12.91231, longitude=74.81231, time_bucket="20260905T10")
    key2 = build_cache_key(namespace="weather", latitude=12.91234, longitude=74.81234, time_bucket="20260905T10")
    assert key1 == key2  # same after rounding to 3 decimals


def test_cache_key_differs_by_namespace() -> None:
    key1 = build_cache_key(namespace="weather", latitude=12.9, longitude=74.8, time_bucket="20260905T10")
    key2 = build_cache_key(namespace="marine", latitude=12.9, longitude=74.8, time_bucket="20260905T10")
    assert key1 != key2


def test_cache_key_never_contains_a_uuid_pattern() -> None:
    key = build_cache_key(namespace="weather", latitude=12.9, longitude=74.8, time_bucket="20260905T10")
    assert "-" not in key.split(":")[-1] or len(key.split(":")[-1]) < 20  # not a uuid4-shaped segment


def test_time_bucket_hourly_quantizes_within_the_hour() -> None:
    t1 = datetime(2026, 9, 5, 10, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 5, 10, 55, tzinfo=timezone.utc)
    assert time_bucket_hourly(t1) == time_bucket_hourly(t2) == "20260905T10"


def test_time_bucket_hourly_differs_across_hours() -> None:
    t1 = datetime(2026, 9, 5, 10, 59, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc)
    assert time_bucket_hourly(t1) != time_bucket_hourly(t2)


def test_cache_hit_after_set(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    key = "orca:agent:weather:test"
    observations = [make_observation()]

    cache.set(key, observations)
    result = cache.get(key)

    assert result is not None
    assert len(result) == 1
    assert result[0].parameter == "wave_height"
    assert result[0].value == 1.2


def test_cache_miss_when_key_absent(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    assert cache.get("orca:agent:weather:absent") is None


def test_cache_none_client_always_misses() -> None:
    cache = AgentCache(None, ttl_seconds=60)
    cache.set("k", [make_observation()])  # must not raise
    assert cache.get("k") is None


def test_cache_corrupted_entry_is_treated_as_miss(fake_redis) -> None:
    fake_redis.store["orca:agent:weather:corrupt"] = "not-valid-json{{{"
    cache = AgentCache(fake_redis, ttl_seconds=60)
    assert cache.get("orca:agent:weather:corrupt") is None


def test_cache_redis_unavailable_get_is_graceful(broken_redis) -> None:
    cache = AgentCache(broken_redis, ttl_seconds=60)
    assert cache.get("any-key") is None  # never raises


def test_cache_redis_unavailable_set_is_graceful(broken_redis) -> None:
    cache = AgentCache(broken_redis, ttl_seconds=60)
    cache.set("any-key", [make_observation()])  # must not raise


def test_cache_does_not_write_empty_observation_list(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    cache.set("orca:agent:weather:empty", [])
    assert "orca:agent:weather:empty" not in fake_redis.store


def test_generic_json_cache_roundtrip(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    cache.set_json("orca:agent:gis:status", {"dataset_name": "gebco_bathymetry", "acquisition_status": "not_acquired"})
    result = cache.get_json("orca:agent:gis:status")
    assert result == {"dataset_name": "gebco_bathymetry", "acquisition_status": "not_acquired"}


def test_generic_json_cache_miss_on_absent_key(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    assert cache.get_json("absent") is None
