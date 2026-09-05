"""Mocked Open-Meteo Marine adapter tests — deterministic, no network access."""
import httpx
import pytest
import respx

from app.data.open_meteo_marine import OpenMeteoMarineAdapter

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

VALID_PAYLOAD = {
    "latitude": 13.04,
    "longitude": 74.29,
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
        # Far in the future so _select_current_step's fallback (before the
        # first available step) deterministically picks index 0, regardless
        # of the wall-clock time the test suite happens to run at.
        "time": ["2099-01-01T00:00", "2099-01-01T01:00"],
        "wave_height": [1.7, 1.7],
        "wave_direction": [243, 243],
        "wave_period": [9.5, 9.5],
        "sea_surface_temperature": [28.5, 28.5],
        "ocean_current_velocity": [1.8, 1.8],
        "ocean_current_direction": [200, 200],
    },
}


def make_adapter() -> OpenMeteoMarineAdapter:
    return OpenMeteoMarineAdapter(base_url=BASE_URL, timeout_seconds=2.0, raw_data_dir=None)


@respx.mock
def test_fetch_and_parse_valid_response() -> None:
    respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=VALID_PAYLOAD))
    adapter = make_adapter()

    raw = adapter.fetch(latitude=13.04, longitude=74.29)
    observations = adapter.parse(raw, mode="live")

    assert len(observations) == 6

    wave_height = next(o for o in observations if o.parameter == "wave_height")
    assert wave_height.value == pytest.approx(1.7)
    assert wave_height.unit == "m"

    current = next(o for o in observations if o.parameter == "ocean_current_velocity")
    assert current.unit == "m/s"
    assert current.value == pytest.approx(0.5)  # 1.8 km/h -> 0.5 m/s

    for obs in observations:
        assert obs.source == "open-meteo-marine"
        assert obs.source_tier == "live"
        assert obs.is_live is True
        assert obs.crs == "EPSG:4326"
