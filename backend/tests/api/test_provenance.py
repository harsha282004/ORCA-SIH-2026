"""HTTP-level tests for GET /api/v1/query/{query_id}/provenance —
architecture.md §27, §34.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.v1 import query as query_module
from app.main import app
from app.provenance.models import DecisionProvenanceGraph
from app.provenance.store import ProvenanceStore
from tests.api.test_query import InMemorySessionStore
from tests.orchestration.conftest import build_nodes, make_marine_result, make_weather_result

client = TestClient(app)


class InMemoryProvenanceStore(ProvenanceStore):
    def __init__(self):
        super().__init__(None, ttl_seconds=3600)
        self._data: dict[str, DecisionProvenanceGraph] = {}

    def get(self, query_id: str):
        return self._data.get(query_id)

    def save(self, provenance: DecisionProvenanceGraph) -> None:
        self._data[provenance.query_id] = provenance


def teardown_function() -> None:
    app.dependency_overrides.pop(query_module.get_orchestration_nodes, None)
    app.dependency_overrides.pop(query_module.get_session_store, None)
    app.dependency_overrides.pop(query_module.get_provenance_store, None)


def test_provenance_for_unknown_query_id_is_a_404_not_a_guess() -> None:
    response = client.get("/api/v1/query/nonexistent-query-id/provenance")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "PROVENANCE_NOT_FOUND"


def test_provenance_is_retrievable_standalone_after_a_completed_query() -> None:
    store = InMemoryProvenanceStore()
    app.dependency_overrides[query_module.get_orchestration_nodes] = lambda: build_nodes(
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)
    )
    app.dependency_overrides[query_module.get_session_store] = lambda: InMemorySessionStore()
    app.dependency_overrides[query_module.get_provenance_store] = lambda: store

    posted = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    query_id = posted.json()["query_id"]
    posted_provenance = posted.json()["provenance"]

    response = client.get(f"/api/v1/query/{query_id}/provenance")
    assert response.status_code == 200
    assert response.json()["data"] == posted_provenance


def test_provenance_survives_the_session_moving_on_to_a_later_turn() -> None:
    store = InMemoryProvenanceStore()
    session_store = InMemorySessionStore()
    app.dependency_overrides[query_module.get_orchestration_nodes] = lambda: build_nodes(
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0), marine_result=make_marine_result(wave_height=0.5)
    )
    app.dependency_overrides[query_module.get_session_store] = lambda: session_store
    app.dependency_overrides[query_module.get_provenance_store] = lambda: store

    first = client.post("/api/v1/query", json={"query": "Is it safe to fish today?"})
    first_query_id = first.json()["query_id"]
    session_id = first.json()["session_id"]

    client.post("/api/v1/query", json={"query": "What about tomorrow?", "session_id": session_id})

    # The FIRST turn's provenance must still be retrievable on its own, even
    # though the session itself has since moved to the second turn.
    response = client.get(f"/api/v1/query/{first_query_id}/provenance")
    assert response.status_code == 200
    assert response.json()["data"]["query_id"] == first_query_id
