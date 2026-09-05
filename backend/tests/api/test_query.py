"""HTTP-level tests for POST /api/v1/query — architecture.md §31, §34.

Overrides `get_orchestration_nodes`/`get_session_store` with fast, offline
fakes (the same `app.dependency_overrides` pattern Phase 4's
`tests/routing/test_api_route.py` established) — zero network, zero real
Redis, zero LLM API key.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.v1 import query as query_module
from app.main import app
from app.session.store import SessionStore
from tests.orchestration.conftest import build_nodes, make_marine_result, make_raw_intent, make_weather_result

client = TestClient(app)


class InMemorySessionStore(SessionStore):
    def __init__(self):
        super().__init__(None, ttl_seconds=3600)
        self._sessions: dict[str, bytes] = {}

    def get(self, session_id: str):
        import json

        raw = self._sessions.get(session_id)
        if raw is None:
            return None
        from app.session.models import SessionState

        return SessionState.model_validate(json.loads(raw))

    def save(self, session) -> None:
        self._sessions[session.session_id] = session.model_dump_json()


def _override(nodes, store: SessionStore | None = None):
    app.dependency_overrides[query_module.get_orchestration_nodes] = lambda: nodes
    app.dependency_overrides[query_module.get_session_store] = lambda: (store or InMemorySessionStore())


def teardown_function() -> None:
    app.dependency_overrides.pop(query_module.get_orchestration_nodes, None)
    app.dependency_overrides.pop(query_module.get_session_store, None)


def test_happy_path_returns_200_with_decision_and_provenance() -> None:
    _override(build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)))

    response = client.post("/api/v1/query", json={"query": "Is it safe to go fishing today?"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "completed"
    assert body["data"]["decision"]["outcome"] in {"RECOMMEND", "RECOMMEND_WITH_CAUTION", "PROVIDE_ALTERNATIVES", "NO_SAFE_RECOMMENDATION"}
    assert body["provenance"] is not None
    assert body["confidence"] is not None
    assert body["session_id"]
    assert body["query_id"]


def test_empty_query_returns_422() -> None:
    _override(build_nodes())
    response = client.post("/api/v1/query", json={"query": "   "})
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "EMPTY_QUERY"


def test_ambiguous_location_returns_clarification_status_200() -> None:
    _override(build_nodes(raw_intent=make_raw_intent(location_name="Atlantis")))
    response = client.post("/api/v1/query", json={"query": "Is it safe near Atlantis?"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "clarification_needed"
    assert "clarification" in body["data"]


def test_session_id_is_returned_and_can_be_reused_for_a_follow_up_turn() -> None:
    store = InMemorySessionStore()
    _override(build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)), store=store)

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    session_id = first.json()["session_id"]

    second = client.post("/api/v1/query", json={"query": "What about tomorrow?", "session_id": session_id})

    assert second.status_code == 200
    assert second.json()["session_id"] == session_id


def test_response_contains_no_raw_evidence_when_clarification_needed() -> None:
    _override(build_nodes(raw_intent=make_raw_intent(location_name="Atlantis")))
    response = client.post("/api/v1/query", json={"query": "Is it safe near Atlantis?"})
    assert response.json()["evidence"] is None


def test_response_evidence_field_is_populated_on_completion() -> None:
    _override(build_nodes(weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)))
    response = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    assert isinstance(response.json()["evidence"], list)


def test_machine_readable_outcomes_are_never_translated_even_for_non_english_language() -> None:
    _override(
        build_nodes(
            raw_intent=make_raw_intent(language="hi"),
            weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
            marine_result=make_marine_result(wave_height=0.5),
        )
    )
    response = client.post("/api/v1/query", json={"query": "क्या आज मछली पकड़ना सुरक्षित है?"})
    body = response.json()
    assert body["data"]["decision"]["outcome"] in {"RECOMMEND", "RECOMMEND_WITH_CAUTION", "PROVIDE_ALTERNATIVES", "NO_SAFE_RECOMMENDATION"}
    assert body["data"]["safety"]["outcome"] in {"PASS", "BLOCK_BOUNDARY", "BLOCK_MISSING_DATA", "BLOCK_LOW_CONFIDENCE", "BLOCK_HAZARD"}
