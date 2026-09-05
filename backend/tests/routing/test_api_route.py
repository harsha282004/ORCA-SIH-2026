"""HTTP-level tests for POST /api/v1/route — architecture.md §26, §34.

Phase 4 update: the endpoint now does real, bounded live HTTP calls by
default (see app.agents.environmental_provider) — ~10-15s measured (see
docs/data_agents.md §Performance). This offline test suite overrides the
environmental-provider dependency with a fast, deterministic fake (via
`app.dependency_overrides`) so it never depends on network access; the GIS
agent is left as the REAL one (fixture geometry only, no network) so
geofence-blocking behavior is still genuinely exercised. Live agent
behavior itself is covered by `pytest -m live` tests elsewhere.
"""
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import route as route_module
from app.main import app

client = TestClient(app)

# Well inside the demo bbox, west of the fixture "coastline" — open water.
OPEN_WATER_A = {"latitude": 12.80, "longitude": 74.20}
OPEN_WATER_B = {"latitude": 13.30, "longitude": 74.10}

# Inside DEMO_LAND_FIXTURE (lat 12.70-13.45, lon 74.80-75.05).
INSIDE_LAND_FIXTURE = {"latitude": 13.00, "longitude": 74.90}


class FakeEnvironmentalProvider:
    """A fast, offline stand-in satisfying the same constructor/method
    contract as AgentBackedEnvironmentalProvider — no network, no Redis.
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
def _fake_environmental_provider():
    app.dependency_overrides[route_module.get_environmental_provider_class] = lambda: FakeEnvironmentalProvider
    yield
    app.dependency_overrides.pop(route_module.get_environmental_provider_class, None)


def test_route_endpoint_returns_feasible_route_for_open_water() -> None:
    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B})

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] is None
    assert body["data"]["feasibility_status"] == "FEASIBLE"
    assert body["data"]["data_quality"] == "live"  # FakeEnvironmentalProvider reports no synthetic fallback
    assert body["data"]["mode"] == "demo"
    assert "not an official maritime navigation recommendation" in body["data"]["disclaimer"]
    assert body["confidence"] is not None


def test_route_endpoint_rejects_destination_inside_land_fixture() -> None:
    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": INSIDE_LAND_FIXTURE})

    assert response.status_code == 422
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "BLOCKED_LAND_OR_GEOFENCE"


def test_route_endpoint_rejects_origin_outside_domain() -> None:
    response = client.post("/api/v1/route", json={"origin": {"latitude": 0.0, "longitude": 0.0}, "destination": OPEN_WATER_B})

    assert response.status_code == 422
    body = response.json()
    assert body["errors"][0]["code"] == "OUT_OF_DOMAIN"


def test_route_endpoint_rejects_malformed_coordinates_at_request_level() -> None:
    response = client.post("/api/v1/route", json={"origin": {"latitude": 999.0, "longitude": 74.0}, "destination": OPEN_WATER_B})

    # Pydantic's own field validator on Coordinate rejects this before it
    # ever reaches calculate_route — FastAPI's automatic request validation.
    assert response.status_code == 422


def test_route_endpoint_origin_equals_destination() -> None:
    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_A})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["metrics"]["total_distance_km"] == 0.0


def test_route_endpoint_response_contains_no_natural_language_explanation_field() -> None:
    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B})
    body = response.json()
    # Only structured fields — no "explanation"/"rationale" text field of
    # any kind (that remains the Evidence & Explanation Agent's job, Phase 4+).
    assert "explanation" not in body["data"]
    assert "rationale" not in body["data"]


def test_route_endpoint_reports_synthetic_fallback_as_fixture_data_quality() -> None:
    class SyntheticFallbackProvider(FakeEnvironmentalProvider):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.used_synthetic_fallback = True

    app.dependency_overrides[route_module.get_environmental_provider_class] = lambda: SyntheticFallbackProvider
    try:
        response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B})
        assert response.json()["data"]["data_quality"] == "fixture"
    finally:
        app.dependency_overrides[route_module.get_environmental_provider_class] = lambda: FakeEnvironmentalProvider
