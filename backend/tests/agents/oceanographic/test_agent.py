from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.agents.common.cache import AgentCache
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.config import Settings
from app.data.base import SourceAdapter, SourceTimeoutError
from app.data.open_meteo_marine import OpenMeteoMarineAdapter
from app.fabric.spatial import InvalidCoordinateError

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Anchored to real wall-clock time, not a hardcoded date — see the
# equivalent comment in tests/agents/common/test_fallback.py.
NOW = datetime.now(timezone.utc)


def _payload_at(base: datetime) -> dict:
    t0 = base.strftime("%Y-%m-%dT%H:%M")
    t1 = (base + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return {
        "latitude": 13.0,
        "longitude": 74.3,
        "hourly_units": {
            "time": "iso8601",
            "wave_height": "m",
            "wave_direction": "°",
            "wave_period": "s",
            "sea_surface_temperature": "°C",
            "ocean_current_velocity": "km/h",
            "ocean_current_direction": "°",
        },
        "hourly": {
            "time": [t0, t1],
            "wave_height": [1.7, 1.7],
            "wave_direction": [243, 243],
            "wave_period": [9.5, 9.5],
            "sea_surface_temperature": [28.5, 28.5],
            "ocean_current_velocity": [1.8, 1.8],
            "ocean_current_direction": [200, 200],
        },
    }


VALID_PAYLOAD = _payload_at(NOW)


class AlwaysFailAdapter(SourceAdapter):
    source_name = "always-fail-marine"

    def fetch(self, *, latitude, longitude):
        raise SourceTimeoutError("simulated timeout")

    def parse(self, raw, *, mode):
        return []


def make_agent(*, mode: str = "demo", cache: AgentCache | None = None, adapter=None) -> OceanographicIntelligenceAgent:
    settings = Settings(orca_mode=mode)
    adapter = adapter or OpenMeteoMarineAdapter(base_url=BASE_URL, timeout_seconds=2.0)
    cache = cache if cache is not None else AgentCache(None, ttl_seconds=60)
    return OceanographicIntelligenceAgent(adapter=adapter, cache=cache, settings=settings)


@respx.mock
def test_valid_live_response_normalizes_correctly() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent()

    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "ok"
    assert result.source_tier == "live"
    assert result.data["wave_height"] == pytest.approx(1.7)
    assert result.data["ocean_current_velocity"] == pytest.approx(0.5)  # 1.8 km/h -> 0.5 m/s


@respx.mock
def test_live_failure_falls_back_to_cache(fake_redis) -> None:
    cache = AgentCache(fake_redis, ttl_seconds=60)
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent(cache=cache)
    agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    # Same `requested_time` — this test only needs "live down -> cache
    # consulted", avoiding any offset that could cross an hourly cache-key
    # bucket boundary depending on the run time.
    respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="error"))
    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "ok"
    assert result.source_tier == "cached"


@respx.mock
def test_demo_mode_falls_back_to_static() -> None:
    agent = make_agent(mode="demo", adapter=AlwaysFailAdapter(base_url=BASE_URL, timeout_seconds=1.0))
    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "degraded"
    assert result.source_tier == "synthetic"
    assert any("DEMO DATA" in w for w in result.warnings)


def test_live_mode_never_falls_back_to_static() -> None:
    agent = make_agent(mode="live", adapter=AlwaysFailAdapter(base_url=BASE_URL, timeout_seconds=1.0))
    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert result.status == "failed"
    assert result.source_tier != "synthetic"


@respx.mock
def test_malformed_upstream_response() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json={"latitude": 1, "longitude": 2}))
    agent = make_agent(mode="live")

    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)
    assert result.status == "failed"


def test_invalid_coordinates_raise_before_any_fetch() -> None:
    agent = make_agent()
    with pytest.raises(InvalidCoordinateError):
        agent.get_marine(latitude=13.0, longitude=999.0)


@respx.mock
def test_provenance_present_on_success() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    agent = make_agent()
    result = agent.get_marine(latitude=13.0, longitude=74.3, requested_time=NOW)

    assert len(result.evidence) == 6
    assert all(e.source == "open-meteo-marine" for e in result.evidence)
    assert result.spatial_extent == {"type": "Point", "coordinates": [74.3, 13.0]}
