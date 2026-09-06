"""`app.fishing.temporal.evaluate_temporal_suitability` — Phase 3's own real
multi-hour path, previously verified only via live curl (no offline test
existed). Phase 7 adds this offline coverage since new capabilities
(`GET /safety/temporal`, the conversational temporal-window handler) both
build directly on this function. Fake adapters return a REAL-shaped
Open-Meteo hourly payload (matching production units) — never a live call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.gis.agent import GISGeofencingAgent
from app.data.base import RawResponse
from app.fishing.temporal import evaluate_temporal_suitability, select_best_time_by_risk, select_best_time_by_suitability
from app.risk.config import get_risk_config
from app.suitability.config import get_suitability_weights

OPEN_WATER = (12.80, 74.20)


def _now_hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _hourly_times(n: int) -> list[str]:
    base = _now_hour()
    return [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]


class FakeAdapter:
    def __init__(self, *, hourly: dict, units: dict):
        self._hourly = hourly
        self._units = units

    def fetch(self, *, latitude: float, longitude: float) -> RawResponse:
        del latitude, longitude
        return RawResponse(
            source="fake", request_url="fake://test", request_params={},
            retrieved_at=datetime.now(timezone.utc),
            payload={"hourly": self._hourly, "hourly_units": self._units},
        )


def _weather_adapter(*, wind_speeds: list[float], weathercodes: list[int] | None = None) -> FakeAdapter:
    n = len(wind_speeds)
    codes = weathercodes or [1] * n
    return FakeAdapter(
        hourly={"time": _hourly_times(n), "wind_speed_10m": wind_speeds, "weathercode": codes, "temperature_2m": [27.0] * n, "wind_direction_10m": [180.0] * n, "precipitation": [0.0] * n},
        units={"wind_speed_10m": "m/s", "weathercode": "wmocode", "temperature_2m": "°C", "wind_direction_10m": "degree", "precipitation": "mm"},
    )


def _marine_adapter(*, wave_heights: list[float]) -> FakeAdapter:
    n = len(wave_heights)
    return FakeAdapter(
        hourly={"time": _hourly_times(n), "wave_height": wave_heights, "sea_surface_temperature": [28.0] * n, "wave_direction": [180.0] * n, "wave_period": [6.0] * n, "ocean_current_velocity": [0.2] * n, "ocean_current_direction": [90.0] * n},
        units={"wave_height": "m", "sea_surface_temperature": "°C", "wave_direction": "degree", "wave_period": "s", "ocean_current_velocity": "m/s", "ocean_current_direction": "degree"},
    )


def _evaluate(*, wind_speeds, wave_heights, hours=None, weathercodes=None):
    lat, lon = OPEN_WATER
    n = len(wind_speeds)
    return evaluate_temporal_suitability(
        latitude=lat, longitude=lon, hours=hours or n, gis_agent=GISGeofencingAgent(),
        risk_config=get_risk_config(), suitability_weights=get_suitability_weights(),
        weather_adapter=_weather_adapter(wind_speeds=wind_speeds, weathercodes=weathercodes),
        marine_adapter=_marine_adapter(wave_heights=wave_heights),
    )


def test_each_real_hour_produces_a_distinct_timestamp_and_value() -> None:
    series = _evaluate(wind_speeds=[3.0, 5.0, 8.0, 4.0], wave_heights=[0.5, 0.8, 1.2, 0.6])
    assert len(series) == 4
    timestamps = [c.timestamp for c in series]
    assert len(set(timestamps)) == 4  # genuinely distinct, real hours
    assert timestamps == sorted(timestamps)  # chronological
    wave_values = [c.environmental_context.wave_height_m for c in series]
    assert wave_values == [0.5, 0.8, 1.2, 0.6]  # real values preserved exactly, never smoothed


def test_calm_hour_is_ranked_low_risk() -> None:
    series = _evaluate(wind_speeds=[3.0], wave_heights=[0.5])
    assert series[0].status == "ranked"
    assert series[0].risk_level == "LOW"
    assert series[0].decision_outcome == "RECOMMEND"


def test_saturating_wave_hour_is_blocked_by_hazard_awareness() -> None:
    series = _evaluate(wind_speeds=[3.0], wave_heights=[3.5])  # >= WAVE_SATURATION_M
    assert series[0].status == "avoid"
    assert series[0].safety_outcome == "BLOCK_HAZARD"
    assert series[0].decision_outcome == "NO_SAFE_RECOMMENDATION"


def test_best_time_by_risk_picks_lowest_risk_among_safe_hours() -> None:
    # Hour 0: calm. Hour 1: rough but still ranked. Hour 2: saturating -> blocked.
    series = _evaluate(wind_speeds=[3.0, 10.0, 3.0], wave_heights=[0.5, 1.8, 3.5])
    best = select_best_time_by_risk(series)
    assert best == 0  # the calmest SAFE hour, never the blocked one despite its low index proximity


def test_best_time_by_risk_never_selects_a_blocked_hour_even_if_only_option() -> None:
    series = _evaluate(wind_speeds=[25.0], wave_heights=[3.9])  # every hour blocked
    assert select_best_time_by_risk(series) is None


def test_best_time_by_suitability_matches_pre_existing_fishing_temporal_semantics() -> None:
    series = _evaluate(wind_speeds=[3.0, 12.0], wave_heights=[0.4, 2.0])
    best = select_best_time_by_suitability(series)
    assert best == 0


def test_missing_hourly_variable_is_insufficient_data_not_a_fabricated_value() -> None:
    lat, lon = OPEN_WATER
    weather = FakeAdapter(
        hourly={"time": _hourly_times(1), "wind_speed_10m": [None], "weathercode": [1], "temperature_2m": [27.0], "wind_direction_10m": [180.0], "precipitation": [0.0]},
        units={"wind_speed_10m": "m/s", "weathercode": "wmocode", "temperature_2m": "°C", "wind_direction_10m": "degree", "precipitation": "mm"},
    )
    marine = _marine_adapter(wave_heights=[0.5])
    series = evaluate_temporal_suitability(
        latitude=lat, longitude=lon, hours=1, gis_agent=GISGeofencingAgent(), risk_config=get_risk_config(),
        suitability_weights=get_suitability_weights(), weather_adapter=weather, marine_adapter=marine,
    )
    assert series[0].status == "insufficient_data"


def test_deterministic_repeatability() -> None:
    kwargs = dict(wind_speeds=[3.0, 6.0, 9.0], wave_heights=[0.5, 1.0, 1.6])
    a = [c.risk_score for c in _evaluate(**kwargs)]
    b = [c.risk_score for c in _evaluate(**kwargs)]
    assert a == b
