"""Tests for app.agents.environmental_provider — the bridge between the
Weather/Oceanographic agents and Phase 3's routing engine. No real
network access; the Weather/Oceanographic agents are stubbed directly.
"""
from datetime import datetime, timezone

from app.agents.environmental_provider import AgentBackedEnvironmentalProvider, generate_sample_points
from app.gis.grid import GridCell
from app.models.contracts import AgentResult
from app.models.geo import BBox
from shapely.geometry import Polygon

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)


def make_cell(lat: float, lon: float) -> GridCell:
    return GridCell(
        cell_id=f"r0c0-{lat}-{lon}", row=0, col=0,
        geometry=Polygon([(lon, lat), (lon + 0.01, lat), (lon + 0.01, lat + 0.01), (lon, lat + 0.01)]),
        centroid_lat=lat, centroid_lon=lon,
    )


def make_result(*, status="ok", data=None, confidence=1.0, temporal_validity_status="VALID", source_tier="live") -> AgentResult:
    return AgentResult(
        status=status, data=data or {}, evidence=[], confidence=confidence, source_tier=source_tier,
        timestamp=NOW, spatial_extent={"type": "Point", "coordinates": [74.0, 12.0]},
        temporal_validity={"valid_from": None, "valid_to": None, "is_forecast": True},
        mode="demo", temporal_validity_status=temporal_validity_status,
    )


class StubWeatherAgent:
    def __init__(self, result: AgentResult):
        self._result = result
        self.calls: list[tuple[float, float]] = []

    def get_weather(self, *, latitude, longitude, requested_time=None):
        self.calls.append((latitude, longitude))
        return self._result


class StubOceanographicAgent:
    def __init__(self, result: AgentResult):
        self._result = result
        self.calls: list[tuple[float, float]] = []

    def get_marine(self, *, latitude, longitude, requested_time=None):
        self.calls.append((latitude, longitude))
        return self._result


class StubGISAgent:
    def nearest_hard_geofence_distance_km(self, latitude, longitude, **kwargs):
        return None  # no hard geofences in range for these tests


def test_generate_sample_points_is_deterministic() -> None:
    points1 = generate_sample_points(BBOX, samples_per_axis=4)
    points2 = generate_sample_points(BBOX, samples_per_axis=4)
    assert points1 == points2
    assert len(points1) == 16


def test_generate_sample_points_rejects_invalid_axis_count() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_sample_points(BBOX, samples_per_axis=0)


def test_generate_sample_points_within_bbox() -> None:
    points = generate_sample_points(BBOX, samples_per_axis=3)
    for lat, lon in points:
        assert BBOX.min_lat <= lat <= BBOX.max_lat
        assert BBOX.min_lon <= lon <= BBOX.max_lon


def test_provider_assigns_nearest_sample_to_cell() -> None:
    weather = StubWeatherAgent(make_result(data={"wind_speed_10m": 2.0, "weathercode": 1, "temperature_2m": 27.0, "wind_direction_10m": 200.0, "precipitation": 0.0}))
    marine = StubOceanographicAgent(make_result(data={"wave_height": 0.5, "wave_period": 6.0, "wave_direction": 200.0, "sea_surface_temperature": 28.0, "ocean_current_velocity": 0.1, "ocean_current_direction": 180.0}))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=2,
    )
    provider.prepare(BBOX)

    cell = make_cell(12.05, 74.05)
    risk = provider.risk_provider(cell)
    hazard = provider.hazard_provider(cell)

    assert 0.0 <= risk <= 1.0
    assert hazard == 0.0  # weathercode=1 is not a thunderstorm code
    assert len(weather.calls) == 4  # 2x2 sample grid
    assert len(marine.calls) == 4


def test_provider_uses_maximally_risky_score_when_weather_failed() -> None:
    weather = StubWeatherAgent(make_result(status="failed", data={}))
    marine = StubOceanographicAgent(make_result(data={"wave_height": 0.1}))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)

    cell = make_cell(12.15, 74.15)
    assert provider.risk_provider(cell) == 1.0  # "unknown is risky, not safe"
    assert provider.hazard_provider(cell) == 0.0


def test_provider_thunderstorm_weathercode_produces_hazard() -> None:
    weather = StubWeatherAgent(make_result(data={"wind_speed_10m": 2.0, "weathercode": 95, "temperature_2m": 27.0, "wind_direction_10m": 200.0, "precipitation": 0.0}))
    marine = StubOceanographicAgent(make_result(data={"wave_height": 0.5, "wave_period": 6.0, "wave_direction": 200.0, "sea_surface_temperature": 28.0, "ocean_current_velocity": 0.1, "ocean_current_direction": 180.0}))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)

    cell = make_cell(12.15, 74.15)
    assert provider.hazard_provider(cell) == 1.0


def test_provider_overall_temporal_validity_rolls_up_worst_case() -> None:
    weather = StubWeatherAgent(make_result(temporal_validity_status="STALE"))
    marine = StubOceanographicAgent(make_result(temporal_validity_status="VALID"))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)
    assert provider.overall_temporal_validity == "STALE"


def test_provider_overall_confidence_is_minimum_across_sites() -> None:
    weather = StubWeatherAgent(make_result(confidence=0.9))
    marine = StubOceanographicAgent(make_result(confidence=0.3))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)
    assert provider.overall_confidence == 0.3


def test_provider_detects_synthetic_fallback_usage() -> None:
    weather = StubWeatherAgent(make_result(source_tier="synthetic"))
    marine = StubOceanographicAgent(make_result(source_tier="live"))
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)
    assert provider.used_synthetic_fallback is True


def test_provider_raises_if_used_before_prepare() -> None:
    import pytest

    provider = AgentBackedEnvironmentalProvider(
        weather_agent=StubWeatherAgent(make_result()), oceanographic_agent=StubOceanographicAgent(make_result()),
        gis_agent=StubGISAgent(),
    )
    with pytest.raises(RuntimeError):
        provider.risk_provider(make_cell(12.1, 74.1))


def test_provider_is_deterministic() -> None:
    weather = StubWeatherAgent(make_result(data={"wind_speed_10m": 5.0, "weathercode": 3, "temperature_2m": 27.0, "wind_direction_10m": 200.0, "precipitation": 0.0}))
    marine = StubOceanographicAgent(make_result(data={"wave_height": 1.0, "wave_period": 7.0, "wave_direction": 200.0, "sea_surface_temperature": 28.0, "ocean_current_velocity": 0.2, "ocean_current_direction": 180.0}))
    cell = make_cell(12.1, 74.1)

    scores = set()
    for _ in range(5):
        provider = AgentBackedEnvironmentalProvider(
            weather_agent=weather, oceanographic_agent=marine, gis_agent=StubGISAgent(), samples_per_axis=3,
        )
        provider.prepare(BBOX)
        scores.add(provider.risk_provider(cell))
    assert len(scores) == 1
