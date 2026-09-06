"""HTTP-level tests for GET /api/v1/safety/* — Phase 4. Runs entirely
offline via `app.dependency_overrides` (no live HTTP to Open-Meteo or
GDACS), mirroring tests/api/test_fishing.py's own pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import safety as safety_module
from app.hazard.cyclone import CYCLONE_CACHE_KEY
from app.main import app
from app.models.contracts import AgentResult

client = TestClient(app)
NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
POINT = {"latitude": 12.8, "longitude": 74.2}


def _agent_result(*, data: dict, lat: float, lon: float, status: str = "ok") -> AgentResult:
    return AgentResult(
        status=status, data=data, evidence=[], confidence=0.9, source_tier="live", timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo", temporal_validity_status="VALID",
    )


class FakeCache:
    """In-memory stand-in for AgentCache — no Redis, no network. Tests
    control cyclone-source behavior entirely through what (if anything) is
    pre-seeded under CYCLONE_CACHE_KEY, never by hitting GDACS.
    """

    def __init__(self, seed: dict | None = None):
        self._store: dict[str, object] = dict(seed or {})

    def get_json(self, key: str):
        return self._store.get(key)

    def set_json(self, key: str, value) -> None:
        self._store[key] = value


def _make_weather(wind_speed: float = 4.0, weathercode: int = 1):
    class FakeWeatherAgent:
        def get_weather(self, *, latitude, longitude, requested_time=None):
            del requested_time
            return _agent_result(data={"wind_speed_10m": wind_speed, "weathercode": weathercode}, lat=latitude, lon=longitude)

    return FakeWeatherAgent()


def _make_marine(wave_height: float = 0.6):
    class FakeOceanographicAgent:
        def get_marine(self, *, latitude, longitude, requested_time=None):
            del requested_time
            return _agent_result(data={"wave_height": wave_height, "sea_surface_temperature": 28.6}, lat=latitude, lon=longitude)

    return FakeOceanographicAgent()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(safety_module.get_weather_agent, None)
    app.dependency_overrides.pop(safety_module.get_oceanographic_agent, None)
    app.dependency_overrides.pop(safety_module.get_hazard_cache, None)


def _override(*, wind_speed: float = 4.0, weathercode: int = 1, wave_height: float = 0.6, cyclone_seed: dict | None = None):
    app.dependency_overrides[safety_module.get_weather_agent] = lambda: _make_weather(wind_speed, weathercode)
    app.dependency_overrides[safety_module.get_oceanographic_agent] = lambda: _make_marine(wave_height)
    # Default: cyclone cache pre-seeded EMPTY (a "cached" hit with zero
    # events) so tests never depend on live GDACS reachability.
    app.dependency_overrides[safety_module.get_hazard_cache] = lambda: FakeCache(cyclone_seed or {CYCLONE_CACHE_KEY: []})


def test_status_rejects_point_outside_demo_bbox() -> None:
    _override()
    response = client.get("/api/v1/safety/status", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_status_is_safe_under_calm_conditions_with_no_hazards() -> None:
    _override(wind_speed=4.0, wave_height=0.5)
    response = client.get("/api/v1/safety/status", params=POINT)
    assert response.status_code == 200
    body = response.json()
    assert body["errors"] is None
    assert body["data"]["level"] == "SAFE"
    assert body["data"]["hazards"] == []
    # lightning is always disclosed as unavailable, never silently omitted
    types = {s["hazard_type"] for s in body["data"]["unavailable_sources"]}
    assert "THUNDERSTORM_PROXY" in types


def test_status_is_danger_when_wave_height_saturates_risk_engine_threshold() -> None:
    _override(wave_height=3.6)  # above WAVE_SATURATION_M
    response = client.get("/api/v1/safety/status", params=POINT)
    body = response.json()
    assert body["data"]["level"] == "DANGER"
    hazard_types = {h["hazard_type"] for h in body["data"]["hazards"]}
    assert "HIGH_WAVES" in hazard_types


def test_status_is_caution_or_worse_under_advisory_band_wind() -> None:
    _override(wind_speed=15.0)  # 75% of WIND_SATURATION_MS=20.0 -> ADVISORY
    response = client.get("/api/v1/safety/status", params=POINT)
    body = response.json()
    assert body["data"]["level"] in ("CAUTION", "WARNING", "DANGER")
    hazard_types = {h["hazard_type"] for h in body["data"]["hazards"]}
    assert "HIGH_WIND" in hazard_types


def test_status_is_unknown_not_safe_when_cyclone_source_is_unavailable(monkeypatch) -> None:
    _override(wind_speed=4.0, wave_height=0.5)

    def _raise(**_kwargs):
        from app.hazard.cyclone import CycloneSourceError

        raise CycloneSourceError("simulated GDACS outage")

    monkeypatch.setattr("app.hazard.cyclone.fetch_active_cyclones_raw", _raise)
    # empty cache forces a real fetch attempt, which the monkeypatch fails
    app.dependency_overrides[safety_module.get_hazard_cache] = lambda: FakeCache({})

    response = client.get("/api/v1/safety/status", params=POINT)
    body = response.json()
    assert body["data"]["level"] == "UNKNOWN"
    assert any(s["hazard_type"] == "CYCLONE" and s["status"] == "UNAVAILABLE" for s in body["data"]["unavailable_sources"])


def test_hazards_endpoint_rejects_point_outside_demo_bbox() -> None:
    _override()
    response = client.get("/api/v1/safety/hazards", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_hazards_endpoint_returns_geojson_with_calm_conditions_empty() -> None:
    _override(wind_speed=4.0, wave_height=0.5)
    response = client.get("/api/v1/safety/hazards", params=POINT)
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["type"] == "FeatureCollection"
    assert body["data"]["features"] == []
    assert body["meta"]["hazard_count"] == 0
    assert len(body["meta"]["unavailable_sources"]) >= 1


def test_hazards_endpoint_reports_real_feature_with_point_geometry_on_danger_wave() -> None:
    _override(wave_height=3.6)
    response = client.get("/api/v1/safety/hazards", params=POINT)
    body = response.json()
    features = body["data"]["features"]
    assert len(features) >= 1
    wave_features = [f for f in features if f["properties"]["hazard_type"] == "HIGH_WAVES"]
    assert len(wave_features) == 1
    assert wave_features[0]["geometry"]["type"] == "Point"
    assert wave_features[0]["properties"]["severity"] == "DANGER"
    assert wave_features[0]["properties"]["is_authoritative"] is False


def test_sources_endpoint_lists_all_five_hazard_categories_honestly() -> None:
    response = client.get("/api/v1/safety/sources")
    assert response.status_code == 200
    body = response.json()
    sources = body["data"]["sources"]
    hazard_types = {s["hazard_type"] for s in sources}
    assert hazard_types == {"CYCLONE", "THUNDERSTORM_PROXY", "HIGH_WIND", "HIGH_WAVES", "GEOFENCE_BOUNDARY"}
    lightning = next(s for s in sources if s["hazard_type"] == "THUNDERSTORM_PROXY")
    assert lightning["status"] == "UNAVAILABLE"


def test_status_is_deterministic_given_identical_inputs() -> None:
    _override(wind_speed=4.0, wave_height=0.5)
    r1 = client.get("/api/v1/safety/status", params=POINT).json()
    r2 = client.get("/api/v1/safety/status", params=POINT).json()
    for key in ("level", "reason", "decision_outcome", "safety_guard_outcome", "risk_level"):
        assert r1["data"][key] == r2["data"][key]


# --- GET /safety/temporal — Phase 7 ---------------------------------------
#
# Reuses `app.fishing.temporal.evaluate_temporal_suitability` (its own real
# behavior is covered offline by tests/fishing/test_temporal.py with fake
# adapters); this endpoint has no adapter-injection seam of its own (same
# pre-existing limitation as `GET /fishing/temporal`), so only the
# request-validation path is tested at the HTTP level, consistent with
# that endpoint's own established offline-test pattern.


def test_temporal_rejects_point_outside_demo_bbox() -> None:
    response = client.get("/api/v1/safety/temporal", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"
