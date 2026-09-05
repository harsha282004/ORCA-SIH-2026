from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.agents.common.cache import AgentCache
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import Settings
from app.data.base import SourceAdapter, SourceTimeoutError
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter
from app.fabric.spatial import InvalidCoordinateError

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Anchored to real wall-clock time, not a hardcoded date — see the
# equivalent comment in tests/agents/common/test_fallback.py for why a
# fixed date would silently desync from `_select_current_step`'s use of
# the actual `retrieved_at` and flip the Temporal Validity Gate's verdict.
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


class AlwaysFailAdapter(SourceAdapter):
    source_name = "always-fail-weather"

    def fetch(self, *, latitude, longitude):
        raise SourceTimeoutError("simulated timeout")

    def parse(self, raw, *, mode):
        return []


def make_agent(*, mode: str = "demo", cache: AgentCache | None = None, adapter=None) -> WeatherIntelligenceAgent:
    settings = Settings(orca_mode=mode)
    adapter = adapter or OpenMeteoWeatherAdapter(base_url=BASE_URL, timeout_seconds=2.0)
    cache = cache if cache is not None else AgentCache(None, ttl_seconds=60)
    return WeatherIntelligenceAgent(adapter=adapter, cache=cache, settings=settings)


@respx.mock
def test_valid_live_response_normalizes_correctly() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent()

    result = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "ok"
    assert result.source_tier == "live"
    assert result.mode == "demo"
    assert result.temporal_validity_status == "VALID"
    assert result.data["wind_speed_10m"] == pytest.approx(5.0)  # 18 km/h -> 5 m/s, reusing Phase 1 normalization


@respx.mock
def test_live_failure_falls_back_to_cache(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent(cache=cache)
    agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)  # populates cache

    # Same `requested_time` — this test only needs "live down -> cache
    # consulted", not staleness, so it avoids any offset that could cross
    # an hourly cache-key bucket boundary depending on the run time.
    respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="error"))
    result = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "ok"
    assert result.source_tier == "cached"


@respx.mock
def test_demo_mode_falls_back_to_static_when_all_sources_unavailable() -> None:
    agent = make_agent(mode="demo", adapter=AlwaysFailAdapter(base_url=BASE_URL, timeout_seconds=1.0))
    result = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "degraded"
    assert result.source_tier == "synthetic"
    assert any("DEMO DATA" in w for w in result.warnings)


def test_live_mode_never_falls_back_to_static() -> None:
    agent = make_agent(mode="live", adapter=AlwaysFailAdapter(base_url=BASE_URL, timeout_seconds=1.0))
    result = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "failed"
    assert result.source_tier != "synthetic"
    assert result.data == {}


def test_invalid_coordinates_raise_before_any_fetch() -> None:
    agent = make_agent()
    with pytest.raises(InvalidCoordinateError):
        agent.get_weather(latitude=999.0, longitude=74.3)


@respx.mock
def test_malformed_upstream_data_in_live_mode_falls_through_correctly() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json={"latitude": 1, "longitude": 2}))  # missing 'hourly'
    agent = make_agent(mode="live")

    result = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "failed"  # malformed live response -> SourceResponseError -> no cache -> failed


@respx.mock
def test_cache_key_determinism_across_calls(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent(cache=cache)

    # Same `requested_time` for both — this test is about coordinate
    # quantization, not the hour bucket, so it avoids any offset that
    # could cross an hourly boundary depending on the run time.
    agent.get_weather(latitude=13.0001, longitude=74.3001, requested_time=NOW)
    agent.get_weather(latitude=13.0002, longitude=74.3002, requested_time=NOW)

    # Both calls quantize to the same cache key (same rounded coordinates,
    # same hour bucket) -> exactly one cache entry, not two.
    assert len(fake_redis.store) == 1


@respx.mock
def test_ttl_is_applied_from_settings(fake_redis) -> None:
    settings = Settings(orca_mode="demo", weather_cache_ttl_seconds=42)
    cache = AgentCache(fake_redis, ttl_seconds=settings.weather_cache_ttl_seconds)
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = WeatherIntelligenceAgent(
        adapter=OpenMeteoWeatherAdapter(base_url=BASE_URL, timeout_seconds=2.0), cache=cache, settings=settings
    )
    agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)
    assert cache.ttl_seconds == 42


def test_result_is_deterministic_for_repeated_calls_against_same_cache(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    with respx.mock:
        respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
        agent = make_agent(cache=cache)
        first = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)

    with respx.mock:
        respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="down"))
        second = agent.get_weather(latitude=13.0, longitude=74.3, requested_time=NOW)  # served from cache, same requested_time

    assert first.data == second.data
    assert first.temporal_validity_status == second.temporal_validity_status
