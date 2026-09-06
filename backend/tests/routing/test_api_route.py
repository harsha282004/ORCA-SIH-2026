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


class FakeHazardCache:
    """Phase 4: an in-memory, network-free stand-in for `AgentCache`,
    pre-seeded with an EMPTY cyclone list so `hazards_near_route` never
    attempts a live GDACS request in this offline test suite.
    """

    def __init__(self):
        from app.hazard.cyclone import CYCLONE_CACHE_KEY

        self._store: dict = {CYCLONE_CACHE_KEY: []}

    def get_json(self, key: str):
        return self._store.get(key)

    def set_json(self, key: str, value) -> None:
        self._store[key] = value


@pytest.fixture(autouse=True)
def _fake_environmental_provider():
    app.dependency_overrides[route_module.get_environmental_provider_class] = lambda: FakeEnvironmentalProvider
    app.dependency_overrides[route_module.get_hazard_cache] = lambda: FakeHazardCache()
    yield
    app.dependency_overrides.pop(route_module.get_environmental_provider_class, None)
    app.dependency_overrides.pop(route_module.get_hazard_cache, None)


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
    # Phase 4 §19/20: always present, even when empty — never silently omitted.
    assert body["data"]["hazards_near_route"] == []
    assert body["data"]["hazard_source_tier"] == "cached"  # FakeHazardCache pre-seeds an empty cyclone list


def test_route_endpoint_default_response_includes_route_level_safety_fields() -> None:
    """Phase 5 (task §9/§11): even a plain, single-route request (the
    default, max_alternatives=1) now exposes a deterministic route-level
    risk_level/safety/decision/label — additive fields only, the existing
    metrics/feasibility_status/etc. are untouched.
    """
    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B})
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["label"] == "A"
    assert body["data"]["risk_level"] in ("LOW", "MODERATE", "HIGH")
    assert body["data"]["safety"]["outcome"] in ("PASS", "BLOCK_BOUNDARY", "BLOCK_MISSING_DATA", "BLOCK_LOW_CONFIDENCE", "BLOCK_HAZARD")
    assert body["data"]["decision"]["outcome"] in ("RECOMMEND", "RECOMMEND_WITH_CAUTION", "PROVIDE_ALTERNATIVES", "NO_SAFE_RECOMMENDATION")
    # Default max_alternatives=1 — never a shape-shifting response.
    assert body["alternatives"] == []
    assert body["comparison"] is None


def test_route_endpoint_generates_bounded_alternatives_when_requested() -> None:
    response = client.post(
        "/api/v1/route",
        json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B, "max_alternatives": 3},
    )
    body = response.json()

    assert response.status_code == 200
    assert len(body["alternatives"]) <= 2  # at most max_alternatives - 1 additional routes
    if body["alternatives"]:
        assert body["comparison"] is not None
        assert body["comparison"]["recommended_label"] in ("A",) + tuple(a["label"] for a in body["alternatives"])
        # every alternative carries the same full safety/decision shape as the primary route
        for alt in body["alternatives"]:
            assert alt["risk_level"] in ("LOW", "MODERATE", "HIGH")
            assert "decision" in alt and "safety" in alt
            assert alt["hazards_near_route"] == body["data"]["hazards_near_route"] or isinstance(alt["hazards_near_route"], list)
    else:
        assert body["comparison"] is None


def test_route_endpoint_rejects_max_alternatives_out_of_range() -> None:
    response = client.post(
        "/api/v1/route",
        json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B, "max_alternatives": 6},
    )
    assert response.status_code == 422  # pydantic validation, before any routing logic runs


def test_route_endpoint_reports_a_real_cyclone_hazard_near_the_computed_path(monkeypatch) -> None:
    """Phase 4 §19/20: a cyclone near the route's own path must be
    disclosed in the response, with a real measured distance — never
    silently dropped just because the route itself remains FEASIBLE by the
    existing A*/cost-only definition.
    """
    from app.hazard.cyclone import CYCLONE_CACHE_KEY
    from app.hazard.models import Hazard

    # Well within RELEVANCE_RADIUS_KM (800km) of the OPEN_WATER_A/B corridor.
    near_cyclone = Hazard(
        hazard_type="CYCLONE", severity="CRITICAL", title="Test Cyclone", description="",
        latitude=13.0, longitude=74.5, source="GDACS (test fixture)", is_authoritative=True,
    )

    class SeededCache(FakeHazardCache):
        def __init__(self):
            self._store = {CYCLONE_CACHE_KEY: [near_cyclone.model_dump(mode="json")]}

    app.dependency_overrides[route_module.get_hazard_cache] = lambda: SeededCache()

    response = client.post("/api/v1/route", json={"origin": OPEN_WATER_A, "destination": OPEN_WATER_B})
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["hazard_source_tier"] == "cached"
    hazards = body["data"]["hazards_near_route"]
    assert len(hazards) == 1
    assert hazards[0]["hazard_type"] == "CYCLONE"
    assert hazards[0]["distance_km"] is not None and hazards[0]["distance_km"] >= 0


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
