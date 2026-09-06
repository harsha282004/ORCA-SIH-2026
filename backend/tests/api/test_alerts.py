"""HTTP-level tests for GET /api/v1/alerts — architecture.md §29, §34.

Overrides the weather/oceanographic/GIS agent dependencies with the same
offline fakes `tests/orchestration/conftest.py` already established, and
an in-memory `AlertStore` so dedup/state-transition is exercised across
two real HTTP calls without any real Redis.
"""
from __future__ import annotations

from app.alerts.store import AlertStore
from app.api.v1 import alerts as alerts_module
from app.main import app
from fastapi.testclient import TestClient
from tests.orchestration.conftest import FakeOceanographicAgent, FakeWeatherAgent, make_marine_result, make_weather_result

client = TestClient(app)


class InMemoryAlertStore(AlertStore):
    def __init__(self):
        super().__init__(None, ttl_seconds=3600)
        self._data: dict[str, dict[str, float]] = {}

    def get(self, region_key: str) -> dict[str, float]:
        return dict(self._data.get(region_key, {}))

    def save(self, region_key: str, state: dict[str, float]) -> None:
        self._data[region_key] = dict(state)


def _override(*, weather_result=None, marine_result=None, store: AlertStore | None = None):
    app.dependency_overrides[alerts_module.get_weather_agent] = lambda: FakeWeatherAgent(weather_result)
    app.dependency_overrides[alerts_module.get_oceanographic_agent] = lambda: FakeOceanographicAgent(marine_result)
    app.dependency_overrides[alerts_module.get_alert_store] = lambda: (store or InMemoryAlertStore())


def teardown_function() -> None:
    app.dependency_overrides.pop(alerts_module.get_weather_agent, None)
    app.dependency_overrides.pop(alerts_module.get_oceanographic_agent, None)
    app.dependency_overrides.pop(alerts_module.get_gis_agent, None)
    app.dependency_overrides.pop(alerts_module.get_alert_store, None)


def test_calm_conditions_return_no_alerts() -> None:
    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=0), marine_result=make_marine_result(wave_height=0.3))
    response = client.get("/api/v1/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["alerts"] == []
    assert body["data_unavailable"] is False


def test_hazardous_conditions_return_a_new_alert() -> None:
    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=96), marine_result=make_marine_result(wave_height=0.3))
    response = client.get("/api/v1/alerts")
    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert any(a["hazard_type"] == "lightning_thunderstorm_proxy" and a["state"] == "New" for a in alerts)


def test_sustained_identical_hazard_is_not_repeated_across_calls() -> None:
    store = InMemoryAlertStore()
    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=96), marine_result=make_marine_result(wave_height=0.3), store=store)

    first = client.get("/api/v1/alerts")
    second = client.get("/api/v1/alerts")

    first_types = {a["hazard_type"] for a in first.json()["alerts"]}
    second_alerts = second.json()["alerts"]
    assert "lightning_thunderstorm_proxy" in first_types
    # Same hazard, same severity, second call -> deduplicated away entirely.
    assert all(a["hazard_type"] != "lightning_thunderstorm_proxy" for a in second_alerts)


def test_hazard_clearing_is_reported_as_resolved() -> None:
    store = InMemoryAlertStore()
    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=96), marine_result=make_marine_result(wave_height=0.3), store=store)
    client.get("/api/v1/alerts")

    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=0), marine_result=make_marine_result(wave_height=0.3), store=store)
    second = client.get("/api/v1/alerts")

    alerts = second.json()["alerts"]
    assert any(a["hazard_type"] == "lightning_thunderstorm_proxy" and a["state"] == "Resolved" for a in alerts)


def test_failed_weather_and_marine_data_never_fabricates_an_all_clear() -> None:
    _override(
        weather_result=make_weather_result(status="failed"),
        marine_result=make_marine_result(status="failed"),
    )
    response = client.get("/api/v1/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["data_unavailable"] is True
    assert all(a["hazard_type"] != "risk_threshold" for a in body["alerts"])


def test_explicit_lat_lon_query_params_are_honored() -> None:
    _override(weather_result=make_weather_result(wind_speed_10m=2.0, weathercode=0), marine_result=make_marine_result(wave_height=0.3))
    response = client.get("/api/v1/alerts", params={"lat": 12.9, "lon": 74.8})
    assert response.status_code == 200
    body = response.json()
    assert body["latitude"] == 12.9
    assert body["longitude"] == 74.8
