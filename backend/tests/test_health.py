"""Phase 0 tests — application wiring and health endpoints only.

No marine-intelligence functionality exists yet to test.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_app_loads() -> None:
    assert app is not None
    assert app.title == "ORCA Backend"


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "service": "orca-backend"}


def test_readiness_endpoint_returns_dependency_structure() -> None:
    """The readiness endpoint must always report real per-dependency status,
    never a fabricated blanket "healthy" value — so this test only asserts
    on the response *shape*, not that infrastructure happens to be up.
    """
    response = client.get("/api/v1/health/ready")
    assert response.status_code in (200, 503)

    body = response.json()
    assert body["status"] in ("ready", "not_ready")
    assert set(body["dependencies"].keys()) == {"database", "postgis", "redis"}
    for dependency_status in body["dependencies"].values():
        assert dependency_status in ("healthy", "unhealthy")

    if body["status"] == "ready":
        assert response.status_code == 200
        assert all(v == "healthy" for v in body["dependencies"].values())
    else:
        assert response.status_code == 503
        assert any(v == "unhealthy" for v in body["dependencies"].values())
