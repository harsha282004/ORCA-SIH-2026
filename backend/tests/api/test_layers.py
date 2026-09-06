"""HTTP-level tests for GET /api/v1/layers/* — the Marine Intelligence Map's
data endpoints. Every endpoint is a thin GeoJSON/JSON serialization over an
EXISTING deterministic engine (GIS geofencing, Risk Engine, Fishing
Suitability Engine); these tests assert that reuse, not a second formula,
and run entirely offline via `app.dependency_overrides` (no live HTTP,
mirroring tests/routing/test_api_route.py's own pattern).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import layers as layers_module
from app.main import app
from app.models.contracts import AgentResult

client = TestClient(app)

NOW = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
# Well inside the demo bbox, open water (matches tests/routing/test_api_route.py's OPEN_WATER_A).
SAMPLE_LAT, SAMPLE_LON = 12.80, 74.20


def _agent_result(
    *,
    data: dict,
    confidence: float = 0.9,
    status: str = "ok",
    source_tier: str = "live",
    temporal_validity_status: str = "VALID",
    is_forecast: bool = True,
) -> AgentResult:
    return AgentResult(
        status=status,
        data=data,
        evidence=[],
        confidence=confidence,
        source_tier=source_tier,
        timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [SAMPLE_LON, SAMPLE_LAT]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": is_forecast},
        mode="demo",
        temporal_validity_status=temporal_validity_status,
    )


class FakeWeatherAgent:
    def get_weather(self, *, latitude, longitude, requested_time=None):
        del latitude, longitude, requested_time
        return _agent_result(data={"wind_speed_10m": 5.0, "weathercode": 1, "temperature_2m": 28.0})


class FakeOceanographicAgent:
    def get_marine(self, *, latitude, longitude, requested_time=None):
        del latitude, longitude, requested_time
        return _agent_result(
            data={
                "wave_height": 0.8,
                "wave_direction": 210.0,
                "wave_period": 6.0,
                "sea_surface_temperature": 28.4,
                "ocean_current_velocity": 0.3,
                "ocean_current_direction": 180.0,
            }
        )


class FakeEnvironmentalProvider:
    """Satisfies AgentBackedEnvironmentalProvider's constructor/method
    contract without any network/Redis dependency — identical in spirit to
    tests/routing/test_api_route.py's own fake.
    """

    def __init__(self, *, gis_agent, requested_time, risk_config):
        del gis_agent, requested_time, risk_config
        self.overall_temporal_validity = "VALID"
        self.overall_confidence = 0.9
        self.used_synthetic_fallback = False

    def prepare(self, bbox) -> None:
        del bbox

    def risk_provider(self, cell) -> float:
        del cell
        return 0.1

    def hazard_provider(self, cell) -> float:
        del cell
        return 0.0


@pytest.fixture(autouse=True)
def _offline_overrides():
    app.dependency_overrides[layers_module.get_weather_agent] = lambda: FakeWeatherAgent()
    app.dependency_overrides[layers_module.get_oceanographic_agent] = lambda: FakeOceanographicAgent()
    app.dependency_overrides[layers_module.get_environmental_provider_class] = lambda: FakeEnvironmentalProvider
    yield
    app.dependency_overrides.pop(layers_module.get_weather_agent, None)
    app.dependency_overrides.pop(layers_module.get_oceanographic_agent, None)
    app.dependency_overrides.pop(layers_module.get_environmental_provider_class, None)


# --- geofences --------------------------------------------------------------


def test_geofences_layer_returns_feature_collection_with_disclaimer() -> None:
    response = client.get("/api/v1/layers/geofences")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["type"] == "FeatureCollection"
    assert len(body["data"]["features"]) >= 1
    feature = body["data"]["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert "category" in feature["properties"]
    assert body["meta"]["is_authoritative"] is False  # fixture geofences are demo/illustrative, never authoritative
    assert "DEMO" in body["meta"]["disclaimer"] or "SIMULATION" in body["meta"]["disclaimer"]
    assert body["meta"]["status"] == "STATIC"


# --- bathymetry ---------------------------------------------------------------


class _FakeGisAgentUnacquired:
    def get_bathymetry_status(self) -> dict:
        return {"acquisition_status": "not_acquired", "reason": "no registry row found"}

    def get_chlorophyll_status(self) -> dict:
        return {"acquisition_status": "not_acquired", "reason": "no registry row found"}

    def get_incois_sst_status(self) -> dict:
        return {"acquisition_status": "not_acquired", "reason": "no registry row found"}


class _FakeGisAgentAcquired:
    def get_bathymetry_status(self) -> dict:
        return {
            "acquisition_status": "acquired",
            "source_name": "GEBCO Compilation Group (IHO/IOC UNESCO)",
            "source_url": "https://www.gebco.net/data-products/gridded-bathymetry-data",
            "dataset_version": "GEBCO_2026 Grid",
            "is_authoritative": True,
            "acquired_at": "2026-09-06T10:52:10+00:00",
            "metadata": {"sample_count_with_value": 225, "depth_min_m": -1400.0, "depth_max_m": -1.0},
        }

    def get_chlorophyll_status(self) -> dict:
        return {
            "acquisition_status": "acquired",
            "source_name": "ESSO-INCOIS",
            "source_url": "https://incois.gov.in/geoportal/MFASPFZ/index.html",
            "is_authoritative": True,
            "acquired_at": "2026-09-06T10:52:10+00:00",
            "metadata": {"sample_count_with_value": 51, "value_min": 0.05, "value_max": 1.9},
        }

    def get_incois_sst_status(self) -> dict:
        return {
            "acquisition_status": "acquired",
            "source_name": "ESSO-INCOIS",
            "source_url": "https://incois.gov.in/geoportal/MFASPFZ/index.html",
            "is_authoritative": True,
            "acquired_at": "2026-09-06T11:00:28+00:00",
            "metadata": {"sample_count_with_value": 56, "value_min": 29.63, "value_max": 31.86},
        }


def test_bathymetry_layer_reports_unavailable_honestly() -> None:
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentUnacquired()
    try:
        response = client.get("/api/v1/layers/bathymetry")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    assert response.status_code == 200
    body = response.json()
    assert body["data"] is None
    assert body["meta"]["available"] is False
    assert body["meta"]["status"] == "UNAVAILABLE"
    assert "NOT CURRENTLY AVAILABLE" in body["meta"]["reason"] or body["meta"]["acquisition_status"] == "not_acquired"


def test_bathymetry_layer_serves_real_data_once_acquired(monkeypatch) -> None:
    fixture = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"depth_m": -56.0, "tid": 40.0}, "geometry": {"type": "Point", "coordinates": [74.28, 13.07]}}]}
    monkeypatch.setattr(layers_module, "_load_processed_geojson", lambda filename: fixture if filename == "gebco_bathymetry_orca_bbox.geojson" else None)
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentAcquired()
    try:
        response = client.get("/api/v1/layers/bathymetry")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    body = response.json()
    assert body["data"] == fixture
    assert body["meta"]["available"] is True
    assert body["meta"]["status"] == "STATIC"
    assert body["meta"]["dataset_version"] == "GEBCO_2026 Grid"
    assert body["meta"]["depth_range_m"] == {"min": -1400.0, "max": -1.0}


# --- chlorophyll ---------------------------------------------------------------


def test_chlorophyll_layer_reports_unavailable_honestly() -> None:
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentUnacquired()
    try:
        response = client.get("/api/v1/layers/chlorophyll")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    body = response.json()
    assert body["data"] is None
    assert body["meta"]["status"] == "UNAVAILABLE"


def test_chlorophyll_layer_serves_real_data_once_acquired(monkeypatch) -> None:
    fixture = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"value": 0.21, "unit": "mg/m^3"}, "geometry": {"type": "Point", "coordinates": [74.28, 13.07]}}]}
    monkeypatch.setattr(layers_module, "_load_processed_geojson", lambda filename: fixture if filename == "incois_chl_orca_bbox.geojson" else None)
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentAcquired()
    try:
        response = client.get("/api/v1/layers/chlorophyll")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    body = response.json()
    assert body["data"] == fixture
    assert body["meta"]["status"] == "CURRENT"
    assert body["meta"]["source"] == "ESSO-INCOIS"


# --- risk-surface --------------------------------------------------------------


def test_risk_surface_layer_returns_navigable_and_blocked_cells() -> None:
    response = client.get("/api/v1/layers/risk-surface")

    assert response.status_code == 200
    body = response.json()
    features = body["data"]["features"]
    assert len(features) > 1
    navigable = [f for f in features if f["properties"]["navigable"]]
    blocked = [f for f in features if not f["properties"]["navigable"]]
    assert navigable  # open water exists in the demo bbox
    assert blocked  # DEMO_LAND_FIXTURE blocks part of the bbox
    for f in navigable:
        assert f["properties"]["risk_score"] == 0.1  # FakeEnvironmentalProvider's fixed value
        assert f["properties"]["risk_level"] == "LOW"
    for f in blocked:
        assert f["properties"]["block_reason"] is not None
    assert body["meta"]["data_quality"] == "live"
    assert body["meta"]["source"].startswith("ORCA deterministic Risk Engine")


def test_risk_surface_layer_reports_fixture_quality_on_synthetic_fallback() -> None:
    class SyntheticProvider(FakeEnvironmentalProvider):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.used_synthetic_fallback = True

    app.dependency_overrides[layers_module.get_environmental_provider_class] = lambda: SyntheticProvider
    response = client.get("/api/v1/layers/risk-surface")
    body = response.json()
    assert body["meta"]["data_quality"] == "fixture"
    assert body["meta"]["status"] == "STATIC"


def test_risk_surface_layer_rejects_resolution_exceeding_max_cells() -> None:
    response = client.get("/api/v1/layers/risk-surface", params={"resolution_km": 0.01})

    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "ROUTING_RESOURCE_LIMIT"


# --- oceanography --------------------------------------------------------------


def test_oceanography_layer_returns_real_sample_values_and_marks_chlorophyll_unavailable() -> None:
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentUnacquired()
    try:
        response = client.get("/api/v1/layers/oceanography")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    assert response.status_code == 200
    body = response.json()
    features = body["data"]["features"]
    assert len(features) >= 1
    props = features[0]["properties"]
    assert props["sea_surface_temperature_c"] == 28.4
    assert props["wave_height_m"] == 0.8
    assert props["ocean_current_velocity_ms"] == 0.3
    assert props["status"] == "FORECAST"  # Open-Meteo hourly data is always forecast-sourced
    assert body["meta"]["chlorophyll"]["available"] is False
    # incois_sst is not acquired in this fake — extended block reports it honestly.
    assert body["incois_sst"]["data"] is None
    assert body["incois_sst"]["meta"]["status"] == "UNAVAILABLE"


def test_oceanography_layer_serves_real_incois_sst_once_acquired(monkeypatch) -> None:
    fixture = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"value": 29.8, "unit": "degC"}, "geometry": {"type": "Point", "coordinates": [74.28, 13.07]}}]}
    monkeypatch.setattr(layers_module, "_load_processed_geojson", lambda filename: fixture if filename == "incois_sst_orca_bbox.geojson" else None)
    app.dependency_overrides[layers_module.get_gis_agent] = lambda: _FakeGisAgentAcquired()
    try:
        response = client.get("/api/v1/layers/oceanography")
    finally:
        app.dependency_overrides.pop(layers_module.get_gis_agent, None)

    body = response.json()
    # Open-Meteo's own data/meta stay exactly as before — extension, not replacement.
    assert body["meta"]["source"].startswith("Open-Meteo")
    assert body["incois_sst"]["data"] == fixture
    assert body["incois_sst"]["meta"]["status"] == "CURRENT"
    assert body["incois_sst"]["meta"]["source"] == "ESSO-INCOIS"
    assert body["incois_sst"]["meta"]["sample_count"] == 56


# --- suitability --------------------------------------------------------------


def test_marine_timeseries_rejects_point_outside_demo_bbox() -> None:
    response = client.get("/api/v1/layers/marine-timeseries", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_marine_timeseries_returns_a_genuine_multi_timestep_series() -> None:
    import respx
    import httpx as httpx_module

    weather_payload = {
        "latitude": 12.8, "longitude": 74.2,
        "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h", "wind_direction_10m": "°", "weathercode": "wmo code", "precipitation": "mm"},
        "hourly": {
            "time": ["2026-09-06T00:00", "2026-09-06T01:00", "2026-09-06T02:00"],
            "temperature_2m": [27.0, 27.5, 28.0],
            "wind_speed_10m": [10.0, 11.0, 12.0],
            "wind_direction_10m": [200.0, 205.0, 210.0],
            "weathercode": [1, 1, 2],
            "precipitation": [0.0, 0.0, 0.1],
        },
    }
    marine_payload = {
        "latitude": 12.8, "longitude": 74.2,
        "hourly_units": {"wave_height": "m", "wave_direction": "°", "wave_period": "s", "sea_surface_temperature": "°C", "ocean_current_velocity": "km/h", "ocean_current_direction": "°"},
        "hourly": {
            "time": ["2026-09-06T00:00", "2026-09-06T01:00", "2026-09-06T02:00"],
            "wave_height": [0.8, 0.9, 1.0],
            "wave_direction": [220.0, 225.0, 230.0],
            "wave_period": [6.0, 6.1, 6.2],
            "sea_surface_temperature": [28.4, 28.5, 28.6],
            "ocean_current_velocity": [1.0, 1.1, 1.2],
            "ocean_current_direction": [180.0, 185.0, 190.0],
        },
    }
    with respx.mock:
        respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=httpx_module.Response(200, json=weather_payload))
        respx.get("https://marine-api.open-meteo.com/v1/marine").mock(return_value=httpx_module.Response(200, json=marine_payload))
        response = client.get("/api/v1/layers/marine-timeseries", params={"latitude": 12.8, "longitude": 74.2})

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] is None
    assert body["meta"]["timestamp_count"] == 3
    series = body["data"]["series"]
    assert len(series) == 3  # a genuine T0/T1/T2 series, not one representative value
    assert series[0]["timestamp"] != series[1]["timestamp"] != series[2]["timestamp"]
    assert series[1]["values"]["sea_surface_temperature"] == 28.5
    assert series[2]["values"]["wave_height"] == 1.0


def test_suitability_layer_reuses_real_engine_and_never_claims_pfz() -> None:
    response = client.get("/api/v1/layers/suitability")

    assert response.status_code == 200
    body = response.json()
    features = body["data"]["features"]
    assert len(features) >= 1
    props = features[0]["properties"]
    assert props["label"] == "ORCA Fishing Suitability"
    assert 0.0 <= props["score"] <= 1.0
    assert props["category"] in ("HIGH", "MODERATE", "LOW", "NOT_RECOMMENDED")
    assert props["pfz_reference_status"] == "unavailable"
    assert "not the official PFZ" in props["disclaimer"]
