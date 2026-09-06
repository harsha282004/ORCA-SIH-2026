"""Phase 11 QA finding: `vite`/`vite preview` auto-increments to the next
free port whenever the default (3000/5173) is already taken — reproduced
live (a stale dev server on 3000 pushed a fresh one to 3006), silently
breaking every backend call with CORS's own generic browser-console error,
which the frontend's fetch-based client cannot distinguish from a true
network outage (both surface as "backend is not reachable").
`allow_origin_regex` fixes this for any localhost port; these tests prove
it without spinning up a real browser.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_default_documented_dev_port_is_allowed() -> None:
    response = client.options(
        "/api/v1/health/ready",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_an_arbitrary_fallback_vite_port_is_also_allowed() -> None:
    response = client.options(
        "/api/v1/query",
        headers={"Origin": "http://localhost:3006", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3006"


def test_a_non_localhost_origin_is_still_rejected() -> None:
    # The fix is scoped to localhost only — it must not become an
    # accidental allow-any-origin policy.
    response = client.options(
        "/api/v1/query",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers.get("access-control-allow-origin") is None
