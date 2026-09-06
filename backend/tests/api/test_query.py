"""HTTP-level tests for POST /api/v1/query — architecture.md §31, §34.

Overrides `get_orchestration_nodes`/`get_session_store` with fast, offline
fakes (the same `app.dependency_overrides` pattern Phase 4's
`tests/routing/test_api_route.py` established) — zero network, zero real
Redis, zero LLM API key.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.query_understanding.models import ReferenceDelta
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


def test_multi_turn_offshore_follow_up_shifts_location_deterministically() -> None:
    # architecture.md §31a end-to-end: a follow-up naming a structured
    # distance change ("20 km farther offshore") must deterministically
    # shift the resolved location relative to the PRIOR turn's already-
    # resolved bbox — computed here, never by the LLM (which only ever
    # supplies the free-text place name / structured distance).
    store = InMemorySessionStore()
    raw_intent = make_raw_intent(
        location_name="Mangaluru",
        refers_to_prior=True,
        reference_type="same_query_different_param",
        reference_delta=ReferenceDelta(offshore_distance_km=20),
    )
    _override(
        build_nodes(
            raw_intent=raw_intent,
            weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
            marine_result=make_marine_result(wave_height=0.5),
        ),
        store=store,
    )

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish near Mangaluru today?"})
    session_id = first.json()["session_id"]
    first_location = store.get(session_id).last_intent.location

    # Turn 1 has no prior turn yet, so refers_to_prior is a no-op and the
    # location resolves normally to the named place.
    assert first_location["type"] == "named_place"
    assert first_location["name"] == "Mangaluru"

    second = client.post(
        "/api/v1/query", json={"query": "What about 20 km farther offshore?", "session_id": session_id}
    )
    assert second.status_code == 200
    second_location = store.get(session_id).last_intent.location

    assert "offshore" in second_location["name"]
    first_bbox, second_bbox = first_location["resolved_bbox"], second_location["resolved_bbox"]
    first_center_lon = (first_bbox["min_lon"] + first_bbox["max_lon"]) / 2
    second_center_lon = (second_bbox["min_lon"] + second_bbox["max_lon"]) / 2
    assert second_center_lon < first_center_lon


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


def test_kannada_query_response_language_is_kannada() -> None:
    _override(
        build_nodes(
            raw_intent=make_raw_intent(language="kn"),
            weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
            marine_result=make_marine_result(wave_height=0.5),
        )
    )
    response = client.post("/api/v1/query", json={"query": "ಇಂದು ಮೀನುಗಾರಿಕೆ ಸುರಕ್ಷಿತವೇ?"})
    body = response.json()
    assert body["data"]["language"] == "kn"
    # Same deterministic numeric values regardless of language (task §41).
    assert isinstance(body["data"]["decision"]["risk_score"], float)


# --- Phase 6 (task §32): manual language override -----------------------


def test_language_override_changes_response_language_field() -> None:
    _override(
        build_nodes(
            raw_intent=make_raw_intent(language="en"),
            weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
            marine_result=make_marine_result(wave_height=0.5),
        )
    )
    response = client.post("/api/v1/query", json={"query": "Is it safe to fish today?", "language_override": "kn"})
    body = response.json()
    assert body["data"]["language"] == "kn"


def test_language_override_does_not_change_the_deterministic_decision() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(language="en"),
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
        marine_result=make_marine_result(wave_height=0.5),
    )
    _override(nodes)
    baseline = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"}).json()

    nodes2 = build_nodes(
        raw_intent=make_raw_intent(language="en"),
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
        marine_result=make_marine_result(wave_height=0.5),
    )
    _override(nodes2)
    overridden = client.post("/api/v1/query", json={"query": "Is it safe to fish today?", "language_override": "hi"}).json()

    assert baseline["data"]["decision"]["outcome"] == overridden["data"]["decision"]["outcome"]
    assert baseline["data"]["decision"]["risk_score"] == overridden["data"]["decision"]["risk_score"]
    assert baseline["data"]["safety"]["outcome"] == overridden["data"]["safety"]["outcome"]
    assert overridden["data"]["language"] == "hi"


def test_unsupported_language_override_is_ignored_not_a_crash() -> None:
    _override(
        build_nodes(
            raw_intent=make_raw_intent(language="en"),
            weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
            marine_result=make_marine_result(wave_height=0.5),
        )
    )
    response = client.post("/api/v1/query", json={"query": "Is it safe to fish today?", "language_override": "fr"})
    assert response.status_code == 200
    assert response.json()["data"]["language"] == "en"  # falls back to the detected language, never crashes or fabricates "fr" support
