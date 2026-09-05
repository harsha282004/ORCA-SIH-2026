"""Conditional-edge decider functions — architecture.md §10's orchestration
flow, Phase 5 task spec §14 (route conditionality) and §10 (clarification
short-circuit).

Both deciders return plain node-name strings (a decider returning a LIST
of names fans out to all of them in parallel — confirmed via a live
LangGraph smoke test — used here for the Query Understanding -> [Weather,
Oceanographic, GIS] fan-out).
"""
from __future__ import annotations

from app.orchestration.state import OrchestrationState

QUERY_UNDERSTANDING_BRANCHES = ["weather", "oceanographic", "gis"]


def after_query_understanding(state: OrchestrationState) -> str | list[str]:
    if state.clarification is not None:
        return "clarify"
    return list(QUERY_UNDERSTANDING_BRANCHES)


def after_decision(state: OrchestrationState) -> str:
    """Route is only ever attempted when the query explicitly asked for one
    AND the Safety Guard passed — architecture.md's fail-closed principle
    applied to routing too: ORCA never spends effort computing a route for
    a query it has already decided it cannot safely support (Phase 5 task
    spec §14).
    """
    if (
        state.intent is not None
        and state.intent.requires_route
        and state.safety is not None
        and state.safety.outcome == "PASS"
    ):
        return "route"
    return "evidence"
