from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.agents.common.cache import AgentCache, build_cache_key, time_bucket_hourly
from app.agents.common.fallback import AllSourcesUnavailableError, fetch_with_fallback
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter
from app.models.contracts import NormalizedObservation, QualityMetadata

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Anchored to real wall-clock time at module load, not a hardcoded date:
# `_select_current_step` (app.data.open_meteo_common) picks its "current"
# hourly step by comparing parsed forecast times against the ACTUAL
# `retrieved_at` (set from `datetime.now()` inside the adapter's HTTP
# call), so a fixed historical/future date would drift out of sync with
# whatever real time the test happens to run at and silently flip these
# tests' Temporal Validity Gate outcome (EXPIRED vs VALID vs STALE).
NOW = datetime.now(timezone.utc)


def _payload_at(base: datetime) -> dict:
    t0 = base.strftime("%Y-%m-%dT%H:%M")
    t1 = (base + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return {
        "latitude": 13.0,
        "longitude": 74.3,
        "hourly_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "wind_speed_10m": "km/h",
            "wind_direction_10m": "°",
            "weathercode": "wmo code",
            "precipitation": "mm",
        },
        "hourly": {
            "time": [t0, t1],
            "temperature_2m": [26.5, 26.7],
            "wind_speed_10m": [18.0, 19.0],
            "wind_direction_10m": [245, 246],
            "weathercode": [1, 1],
            "precipitation": [0.0, 0.0],
        },
    }


VALID_PAYLOAD = _payload_at(NOW)


def make_adapter() -> OpenMeteoWeatherAdapter:
    return OpenMeteoWeatherAdapter(base_url=BASE_URL, timeout_seconds=2.0)


@respx.mock
def test_live_success_returns_live_tier_and_caches(fake_redis) -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    cache = AgentCache(fake_redis, ttl_seconds=60)

    observations, tier = fetch_with_fallback(
        adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
        requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
    )

    assert tier == "live"
    assert len(observations) == 5
    assert len(fake_redis.store) == 1  # cached for next time


@respx.mock
def test_live_failure_falls_back_to_cache(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    # Pre-populate the cache as if a prior successful call had cached it.
    # Same `requested_time` for both calls — this test only needs to prove
    # "live down -> cache consulted", not staleness, so it deliberately
    # avoids any wall-clock-relative offset that could cross an hourly
    # cache-key bucket boundary depending on what minute the suite happens
    # to run at.
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    fetch_with_fallback(
        adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
        requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
    )

    respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="server error"))
    observations, tier = fetch_with_fallback(
        adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
        requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
    )

    assert tier == "cached"
    assert len(observations) == 5


def _seed_observation(*, retrieved_at: datetime, valid_from: datetime, valid_to: datetime) -> NormalizedObservation:
    return NormalizedObservation(
        source="open-meteo-weather",
        source_type="forecast",
        source_tier="live",
        parameter="wave_height",
        value=1.2,
        unit="m",
        latitude=13.0,
        longitude=74.3,
        observed_at=valid_from,
        valid_from=valid_from,
        valid_to=valid_to,
        is_forecast=True,
        retrieved_at=retrieved_at,
        mode="demo",
        is_live=True,
        quality=QualityMetadata(),
    )


def test_cache_hit_recomputes_temporal_validity_never_inherits_stale_status(fake_redis) -> None:
    """architecture.md Phase 4 task spec §17: a cache hit must never
    silently keep a stale/valid status from write-time — it is re-evaluated
    against the CURRENT requested_time.

    Directly seeds the cache with a hand-built observation (fully
    controlled retrieved_at/valid window) rather than going through a
    mocked live call — the point under test is the Gate's recomputation on
    cache read, not the live-fetch path itself (already covered by the
    tests above). Both `seed_time` and `much_later` below are fully
    synthetic and fixed (not derived from real wall-clock `NOW`) — the
    cache key itself is hour-bucketed by `requested_time`
    (`build_cache_key`), so seeding under one bucket and looking up
    another would just be a miss, not the "stale hit" this test targets;
    using fixed synthetic times keeps both calls deterministically in the
    same bucket regardless of when the suite actually runs.
    """
    seed_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    much_later = datetime(2026, 6, 1, 10, 45, tzinfo=timezone.utc)  # same hour bucket, 45 min later

    cache = AgentCache(fake_redis, ttl_seconds=3600)
    key = build_cache_key(namespace="weather", latitude=13.0, longitude=74.3, time_bucket=time_bucket_hourly(seed_time))
    cache.set(key, [_seed_observation(retrieved_at=seed_time, valid_from=seed_time, valid_to=seed_time + timedelta(hours=6))])

    with respx.mock:
        respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="server error"))
        observations, tier = fetch_with_fallback(
            adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
            requested_time=much_later, max_staleness=timedelta(minutes=30), mode="demo",
        )

    assert tier == "cached"
    assert all(o.temporal_validity == "STALE" for o in observations)


@respx.mock
def test_all_sources_unavailable_raises(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)  # empty — nothing cached
    respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="server error"))

    with pytest.raises(AllSourcesUnavailableError):
        fetch_with_fallback(
            adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
            requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
        )


@respx.mock
def test_timeout_also_falls_back_to_cache(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    fetch_with_fallback(
        adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
        requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
    )

    respx.get(BASE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    observations, tier = fetch_with_fallback(
        adapter=make_adapter(), cache=cache, namespace="weather", latitude=13.0, longitude=74.3,
        requested_time=NOW, max_staleness=timedelta(minutes=30), mode="demo",
    )
    assert tier == "cached"
