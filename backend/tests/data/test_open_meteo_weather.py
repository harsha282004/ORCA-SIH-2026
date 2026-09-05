"""Mocked Open-Meteo Weather adapter tests — deterministic, no network access."""
import httpx
import pytest
import respx

from app.data.base import SourceHTTPError, SourceResponseError, SourceTimeoutError
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter

BASE_URL = "https://api.open-meteo.com/v1/forecast"

VALID_PAYLOAD = {
    "latitude": 13.04,
    "longitude": 74.28,
    "hourly_units": {
        "time": "iso8601",
        "temperature_2m": "°C",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "°",
        "weathercode": "wmo code",
        "precipitation": "mm",
    },
    "hourly": {
        # Far in the future so _select_current_step's fallback (before the
        # first available step) deterministically picks index 0, regardless
        # of the wall-clock time the test suite happens to run at.
        "time": ["2099-01-01T00:00", "2099-01-01T01:00"],
        "temperature_2m": [26.5, 26.7],
        "wind_speed_10m": [18.0, 19.0],
        "wind_direction_10m": [245, 246],
        "weathercode": [1, 1],
        "precipitation": [0.0, 0.0],
    },
}


def make_adapter() -> OpenMeteoWeatherAdapter:
    return OpenMeteoWeatherAdapter(base_url=BASE_URL, timeout_seconds=2.0, raw_data_dir=None)


@respx.mock
def test_fetch_and_parse_valid_response() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    observations = adapter.parse(raw, mode="live")

    assert len(observations) == 5
    wind = next(o for o in observations if o.parameter == "wind_speed_10m")
    assert wind.unit == "m/s"
    assert wind.value == pytest.approx(5.0)  # 18 km/h -> 5 m/s
    assert wind.source_tier == "live"
    assert wind.is_live is True
    assert wind.quality.is_missing is False


@respx.mock
def test_missing_field_becomes_explicit_missing_observation() -> None:
    payload = dict(VALID_PAYLOAD)
    payload["hourly"] = dict(VALID_PAYLOAD["hourly"])
    del payload["hourly"]["precipitation"]
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=payload))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    observations = adapter.parse(raw, mode="live")

    precipitation = next(o for o in observations if o.parameter == "precipitation")
    assert precipitation.value is None
    assert precipitation.quality.is_missing is True


@respx.mock
def test_null_value_becomes_explicit_missing_observation() -> None:
    payload = dict(VALID_PAYLOAD)
    payload["hourly"] = dict(VALID_PAYLOAD["hourly"])
    payload["hourly"]["temperature_2m"] = [None, 26.7]
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=payload))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    observations = adapter.parse(raw, mode="live")

    temperature = next(o for o in observations if o.parameter == "temperature_2m")
    assert temperature.value is None
    assert temperature.quality.is_missing is True


@respx.mock
def test_unknown_unit_becomes_explicit_missing_observation() -> None:
    payload = dict(VALID_PAYLOAD)
    payload["hourly_units"] = dict(VALID_PAYLOAD["hourly_units"])
    payload["hourly_units"]["wind_speed_10m"] = "furlongs_per_fortnight"
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=payload))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    observations = adapter.parse(raw, mode="live")

    wind = next(o for o in observations if o.parameter == "wind_speed_10m")
    assert wind.value is None
    assert wind.quality.is_missing is True


@respx.mock
def test_malformed_response_missing_hourly_block_raises() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json={"latitude": 1, "longitude": 2}))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    with pytest.raises(SourceResponseError):
        adapter.parse(raw, mode="live")


@respx.mock
def test_invalid_timestamp_raises() -> None:
    payload = dict(VALID_PAYLOAD)
    payload["hourly"] = dict(VALID_PAYLOAD["hourly"])
    payload["hourly"]["time"] = ["not-a-timestamp", "2026-09-05T01:00"]
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=payload))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.28)
    with pytest.raises(SourceResponseError):
        adapter.parse(raw, mode="live")


@respx.mock
def test_http_error_raises() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(500, text="internal error"))
    adapter = make_adapter()

    with pytest.raises(SourceHTTPError):
        adapter.fetch(latitude=13.04, longitude=74.28)


@respx.mock
def test_timeout_raises() -> None:
    respx.get(BASE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    adapter = make_adapter()

    with pytest.raises(SourceTimeoutError):
        adapter.fetch(latitude=13.04, longitude=74.28)


@respx.mock
def test_non_json_response_raises() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, text="not json"))
    adapter = make_adapter()

    with pytest.raises(SourceResponseError):
        adapter.fetch(latitude=13.04, longitude=74.28)


def test_fetch_rejects_invalid_coordinates() -> None:
    adapter = make_adapter()
    with pytest.raises(Exception):
        adapter.fetch(latitude=200.0, longitude=74.28)
