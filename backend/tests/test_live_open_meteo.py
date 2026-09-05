"""Live integration tests against the real Open-Meteo APIs.

Run explicitly with:  pytest -m live
Excluded from the default test run (pytest -m "not integration") along
with the `integration` tests — ordinary unit-test runs never depend on
internet access.
"""
import pytest

from app.config import get_settings
from app.data.open_meteo_marine import OpenMeteoMarineAdapter
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter


@pytest.mark.live
def test_live_open_meteo_weather_responds_and_normalizes() -> None:
    settings = get_settings()
    latitude, longitude = settings.demo_bbox.center()

    adapter = OpenMeteoWeatherAdapter(
        base_url=settings.open_meteo_weather_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    raw = adapter.fetch(latitude=latitude, longitude=longitude)
    observations = adapter.parse(raw, mode=settings.orca_mode)

    assert len(observations) == 5
    assert all(o.source == "open-meteo-weather" for o in observations)
    assert all(o.source_tier == "live" and o.is_live for o in observations)


@pytest.mark.live
def test_live_open_meteo_marine_responds_and_normalizes() -> None:
    settings = get_settings()
    latitude, longitude = settings.demo_bbox.center()

    adapter = OpenMeteoMarineAdapter(
        base_url=settings.open_meteo_marine_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    raw = adapter.fetch(latitude=latitude, longitude=longitude)
    observations = adapter.parse(raw, mode=settings.orca_mode)

    assert len(observations) == 6
    assert all(o.source == "open-meteo-marine" for o in observations)
    assert all(o.source_tier == "live" and o.is_live for o in observations)
