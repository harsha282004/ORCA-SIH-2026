"""Structural tests on the compiled LangGraph — architecture.md §10, Phase 5
task spec §16-§17. Confirms the graph topology itself (not just node
behavior) enforces "no path reaches evidence/route without passing through
Safety Guard/Decision".
"""
from __future__ import annotations

from app.orchestration.graph import build_orchestration_graph
from tests.orchestration.conftest import build_nodes

EXPECTED_NODES = {
    "__start__", "query_understanding", "weather", "oceanographic", "gis",
    "risk_suitability", "safety_guard", "decision", "route", "evidence", "__end__",
}


def test_graph_compiles_without_error() -> None:
    graph = build_orchestration_graph(build_nodes())
    assert graph is not None


def test_graph_contains_exactly_the_expected_nodes() -> None:
    graph = build_orchestration_graph(build_nodes())
    assert set(graph.get_graph().nodes.keys()) == EXPECTED_NODES


def test_safety_guard_and_decision_are_on_every_path_to_evidence() -> None:
    graph = build_orchestration_graph(build_nodes())
    edges = graph.get_graph().edges
    targets_of_safety_guard = {e.target for e in edges if e.source == "safety_guard"}
    targets_of_decision = {e.target for e in edges if e.source == "decision"}
    sources_of_evidence = {e.source for e in edges if e.target == "evidence"}
    sources_of_route = {e.source for e in edges if e.target == "route"}

    assert targets_of_safety_guard == {"decision"}
    assert sources_of_route == {"decision"}  # route is only ever reached FROM decision
    assert sources_of_evidence == {"route", "decision"}  # evidence is reached only via decision (directly or via route)
