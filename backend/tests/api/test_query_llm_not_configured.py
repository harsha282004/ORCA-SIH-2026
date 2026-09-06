"""Phase 11 QA finding: with no `LLM_PROVIDER` configured (this repo's own
default — see `.env.example`), `POST /api/v1/query` used to propagate a raw
`LLMConfigurationError` out of FastAPI's dependency resolution, surfacing as
an opaque, unstructured 500 `"Internal Server Error"` — indistinguishable
from a genuine crash to any caller (verified against a real running
`uvicorn` instance, not just the overridden-dependency test suite, which
had always masked this path). `get_orchestration_nodes` now converts it
into a structured 503, matching architecture.md §38's "fail closed, but
never silently and never opaquely" expectation.

Deliberately does NOT override `get_orchestration_nodes` — this test only
exists to exercise the REAL, un-faked dependency construction path.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_query_with_no_llm_provider_configured_returns_a_structured_503_not_a_raw_crash() -> None:
    response = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "LLM_NOT_CONFIGURED"
    assert "LLM_PROVIDER" in body["detail"]["message"]
