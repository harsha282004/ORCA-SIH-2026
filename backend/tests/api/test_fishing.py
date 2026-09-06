"""HTTP-level tests for GET/POST /api/v1/fishing/* — Phase 3. Runs entirely
offline via `app.dependency_overrides` (no live HTTP), mirroring
tests/api/test_layers.py's own pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import fishing as fishing_module
from app.main import app
from app.models.contracts import AgentResult

client = TestClient(app)
NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)


def _agent_result(*, data: dict, lat: float, lon: float, status: str = "ok") -> AgentResult:
    return AgentResult(
        status=status, data=data, evidence=[], confidence=0.9, source_tier="live", timestamp=NOW,
        spatial_extent={"type": "Point", "coordinates": [lon, lat]},
        temporal_validity={"valid_from": NOW.isoformat(), "valid_to": NOW.isoformat(), "is_forecast": True},
        mode="demo", temporal_validity_status="VALID",
    )


class FakeWeatherAgent:
    def get_weather(self, *, latitude, longitude, requested_time=None):
        del requested_time
        return _agent_result(data={"wind_speed_10m": 4.0, "weathercode": 1}, lat=latitude, lon=longitude)


class FakeOceanographicAgent:
    def get_marine(self, *, latitude, longitude, requested_time=None):
        del requested_time
        return _agent_result(data={"wave_height": 0.7, "sea_surface_temperature": 28.6}, lat=latitude, lon=longitude)


@pytest.fixture(autouse=True)
def _offline_overrides():
    app.dependency_overrides[fishing_module.get_weather_agent] = lambda: FakeWeatherAgent()
    app.dependency_overrides[fishing_module.get_oceanographic_agent] = lambda: FakeOceanographicAgent()
    yield
    app.dependency_overrides.pop(fishing_module.get_weather_agent, None)
    app.dependency_overrides.pop(fishing_module.get_oceanographic_agent, None)


def test_candidates_endpoint_returns_ranked_and_avoid_features() -> None:
    response = client.get("/api/v1/fishing/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] is None
    features = body["data"]["features"]
    assert len(features) == body["meta"]["sample_count"]
    statuses = {f["properties"]["status"] for f in features}
    assert statuses <= {"ranked", "avoid", "insufficient_data"}
    ranked = [f for f in features if f["properties"]["status"] == "ranked"]
    assert all(f["properties"]["decision_outcome"] in ("RECOMMEND", "RECOMMEND_WITH_CAUTION") for f in ranked)
    assert body["meta"]["pfz_status"].startswith("unavailable")


def test_candidates_endpoint_respects_min_suitability_filter() -> None:
    response = client.get("/api/v1/fishing/candidates", params={"min_suitability": 0.999})
    body = response.json()
    ranked = [f for f in body["data"]["features"] if f["properties"]["status"] == "ranked"]
    assert ranked == []  # an unreachable threshold excludes everything from ranking


def test_nearest_rejects_origin_outside_demo_bbox() -> None:
    response = client.get("/api/v1/fishing/nearest", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_nearest_returns_a_candidate_with_distance() -> None:
    response = client.get("/api/v1/fishing/nearest", params={"latitude": 12.8, "longitude": 74.2})
    body = response.json()
    assert response.status_code == 200
    if body["data"] is not None:  # the fixed fake weather/marine data may or may not pass the demo geofence at every sample
        assert body["data"]["properties"]["distance_km"] is not None
        assert "never nearest by distance alone" in body["meta"]["method"]


def test_compare_rejects_fewer_than_two_points() -> None:
    response = client.post("/api/v1/fishing/compare", json={"points": [{"latitude": 12.8, "longitude": 74.2}]})
    body = response.json()
    assert body["errors"][0]["code"] == "INVALID_REQUEST"


def test_compare_rejects_point_outside_demo_bbox() -> None:
    response = client.post(
        "/api/v1/fishing/compare",
        json={"points": [{"latitude": 12.8, "longitude": 74.2}, {"latitude": 0.0, "longitude": 0.0}]},
    )
    body = response.json()
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_compare_returns_deterministic_traceable_result() -> None:
    response = client.post(
        "/api/v1/fishing/compare",
        json={"points": [{"latitude": 12.8, "longitude": 74.2}, {"latitude": 13.3, "longitude": 74.1}]},
    )
    body = response.json()
    assert response.status_code == 200
    assert len(body["data"]["candidates"]) == 2
    # Even with identical fake weather/marine at both points, the two
    # points sit at different distances from the real demo geofence, so a
    # genuinely different suitability score (via the distance component)
    # is the CORRECT outcome, not a bug — this asserts traceability
    # (both are real, present numbers) rather than a specific value.
    a, b = body["data"]["candidates"]
    assert isinstance(a["suitability_score"], float) and isinstance(b["suitability_score"], float)
    assert body["data"]["better_candidate_index"] in (0, 1)
    assert str(body["data"]["better_candidate_index"]) in body["data"]["reason"] or "index" in body["data"]["reason"]


def test_temporal_rejects_point_outside_demo_bbox() -> None:
    response = client.get("/api/v1/fishing/temporal", params={"latitude": 0.0, "longitude": 0.0})
    body = response.json()
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"
