"""Conversational query endpoint — architecture.md §10 (orchestration
entrypoint), §31 (multi-turn session), §34 (response envelope).

    POST /api/v1/query {"query": "...", "session_id": "..."}
        -> runs the LangGraph orchestration graph
        -> persists conversational context (not environmental data) to the session
        -> returns {data, evidence, confidence, provenance, errors}

The LLM Provider is resolved once via `app.llm.factory.get_llm_provider`
inside the default `OrchestrationNodes()` — this endpoint itself never
imports a vendor SDK. `get_orchestration_nodes`/`get_session_store` are
FastAPI dependencies specifically so tests can override them with fast,
offline fakes (a `FakeLLMProvider`-backed node set, an in-memory session
store), the same pattern Phase 4's `/route` endpoint already established.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.config import get_settings
from app.orchestration.graph import build_orchestration_graph
from app.orchestration.nodes import OrchestrationNodes
from app.orchestration.state import OrchestrationState
from app.services.cache import get_client as get_redis_client
from app.session.models import SessionState
from app.session.store import SessionStore

router = APIRouter()


def get_orchestration_nodes() -> OrchestrationNodes:
    return OrchestrationNodes()


def get_session_store() -> SessionStore:
    settings = get_settings()
    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001 — client construction is lazy/local; never let it crash request handling
        client = None
    return SessionStore(client, ttl_seconds=settings.session_ttl_seconds)


class QueryAPIRequest(BaseModel):
    query: str
    session_id: str | None = None


class QueryAPIErrorResponse(BaseModel):
    code: str
    message: str


class QueryAPIResponse(BaseModel):
    data: dict | None = None
    evidence: list[dict] | None = None
    confidence: float | None = None
    provenance: dict | None = None
    errors: list[QueryAPIErrorResponse] | None = None
    session_id: str
    query_id: str


@router.post("/query")
def create_query(
    request: QueryAPIRequest,
    response: Response,
    nodes: OrchestrationNodes = Depends(get_orchestration_nodes),
    session_store: SessionStore = Depends(get_session_store),
) -> QueryAPIResponse:
    if not request.query or not request.query.strip():
        response.status_code = 422
        return QueryAPIResponse(
            errors=[QueryAPIErrorResponse(code="EMPTY_QUERY", message="query must not be empty")],
            session_id=request.session_id or "",
            query_id="",
        )

    session = session_store.get_or_create(request.session_id)

    graph = build_orchestration_graph(nodes)
    initial_state = OrchestrationState(query=request.query, session_id=session.session_id, language=session.last_language)
    raw_result = graph.invoke(initial_state)
    final_state = OrchestrationState.model_validate(raw_result)

    session.turn_count += 1
    session.last_query = request.query
    session.last_language = final_state.language
    if final_state.intent is not None:
        session.last_intent = final_state.intent
    if final_state.decision is not None:
        session.last_decision = final_state.decision
    if final_state.provenance is not None:
        session.last_provenance = final_state.provenance
    session_store.save(session)

    if final_state.status == "clarification_needed":
        return QueryAPIResponse(
            data={"status": "clarification_needed", "clarification": final_state.clarification.model_dump(mode="json")},
            session_id=session.session_id,
            query_id=final_state.query_id,
        )

    evidence = []
    if final_state.weather is not None:
        evidence.extend(e.model_dump(mode="json") for e in final_state.weather.evidence)
    if final_state.marine is not None:
        evidence.extend(e.model_dump(mode="json") for e in final_state.marine.evidence)

    data = {
        "status": final_state.status,
        "language": final_state.language,
        "decision": final_state.decision.model_dump(mode="json") if final_state.decision else None,
        "safety": final_state.safety.model_dump(mode="json") if final_state.safety else None,
        "explanation": final_state.explanation.rationale if final_state.explanation else None,
        "used_fallback_template": final_state.explanation.used_fallback_template if final_state.explanation else None,
        "route_note": final_state.route_note,
    }

    return QueryAPIResponse(
        data=data,
        evidence=evidence,
        confidence=final_state.decision.confidence if final_state.decision else None,
        provenance=final_state.provenance.model_dump(mode="json") if final_state.provenance else None,
        session_id=session.session_id,
        query_id=final_state.query_id,
    )
