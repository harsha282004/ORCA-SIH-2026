"""HTTP-level tests for POST /api/v1/scenario — architecture.md §32, §34.

Reuses `tests/api/test_query.py`'s `InMemorySessionStore` and
`tests/orchestration/conftest.py`'s offline node builders so this suite
makes zero network/Redis/LLM calls, same as every other API test.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.api.v1 import query as query_module
from app.api.v1 import scenario as scenario_module
from app.llm.fake import FakeLLMProvider
from app.main import app
from tests.api.test_query import InMemorySessionStore, _override
from tests.orchestration.conftest import build_nodes, make_marine_result, make_weather_result

client = TestClient(app)


def _fake_evidence_agent(rationale: str = "Scenario test explanation.") -> EvidenceExplanationAgent:
    return EvidenceExplanationAgent(llm_provider=FakeLLMProvider(structured_response=ExplanationOutput(rationale=rationale)))


def teardown_function() -> None:
    app.dependency_overrides.pop(query_module.get_orchestration_nodes, None)
    app.dependency_overrides.pop(query_module.get_session_store, None)
    app.dependency_overrides.pop(scenario_module.get_session_store, None)
    app.dependency_overrides.pop(scenario_module.get_evidence_agent, None)


def test_scenario_without_a_prior_query_returns_a_controlled_error_not_a_guess() -> None:
    store = InMemorySessionStore()
    _override(build_nodes(), store=store)
    app.dependency_overrides[scenario_module.get_session_store] = lambda: store

    # A session_id that was never used for a /query call.
    response = client.post("/api/v1/scenario", json={"session_id": "never-used-session", "wave_height_delta_m": 1.0})

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "SESSION_NOT_FOUND"


def test_scenario_after_a_completed_query_returns_a_labeled_diffed_result() -> None:
    store = InMemorySessionStore()
    _override(
        build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)),
        store=store,
    )
    app.dependency_overrides[scenario_module.get_session_store] = lambda: store
    app.dependency_overrides[scenario_module.get_evidence_agent] = lambda: _fake_evidence_agent()

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    session_id = first.json()["session_id"]

    response = client.post("/api/v1/scenario", json={"session_id": session_id, "wave_height_delta_m": 3.0})

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["label"] == "SIMULATION — NOT LIVE DATA"
    assert body["scenario"]["decision"]["risk_score"] >= body["baseline"]["decision"]["risk_score"]


def test_scenario_with_no_perturbation_fields_is_a_422() -> None:
    store = InMemorySessionStore()
    _override(
        build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)),
        store=store,
    )
    app.dependency_overrides[scenario_module.get_session_store] = lambda: store
    app.dependency_overrides[scenario_module.get_evidence_agent] = lambda: _fake_evidence_agent()

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    session_id = first.json()["session_id"]

    response = client.post("/api/v1/scenario", json={"session_id": session_id})
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "INVALID_PERTURBATION"


def test_scenario_never_overwrites_the_real_session_baseline() -> None:
    store = InMemorySessionStore()
    _override(
        build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)),
        store=store,
    )
    app.dependency_overrides[scenario_module.get_session_store] = lambda: store
    app.dependency_overrides[scenario_module.get_evidence_agent] = lambda: _fake_evidence_agent()

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    session_id = first.json()["session_id"]
    baseline_decision_before = store.get(session_id).last_decision.model_dump()

    client.post("/api/v1/scenario", json={"session_id": session_id, "wave_height_delta_m": 5.0})

    baseline_decision_after = store.get(session_id).last_decision.model_dump()
    assert baseline_decision_after == baseline_decision_before
