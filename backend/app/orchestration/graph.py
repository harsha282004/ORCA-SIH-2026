"""The ORCA LangGraph orchestration graph — architecture.md §10.

    START -> query_understanding
                |-- clarification needed -----------------------------> END
                '-- continue -> [weather, oceanographic, gis]  (parallel)
                                        |
                                        v
                                 risk_suitability   (fan-in: waits for all three)
                                        |
                                        v
                                  safety_guard
                                        |
                                        v
                                    decision
                                  /          \\
                       requires_route          (default)
                     & safety PASS                 |
                            |                       |
                            v                       |
                          route                     |
                            \\                      /
                             '--------> evidence <--'
                                          |
                                          v
                                         END

The Safety Guard and Decision Engine are always on the only path to
`evidence` — there is no edge that reaches `evidence` or `route` without
first passing through them (Phase 5 task spec §17's "the LLM must never be
able to bypass the Safety Guard/Decision Engine", enforced structurally by
the graph topology itself, not by a runtime check).
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.orchestration.edges import after_decision, after_query_understanding
from app.orchestration.nodes import OrchestrationNodes
from app.orchestration.state import OrchestrationState


def build_orchestration_graph(nodes: OrchestrationNodes | None = None) -> CompiledStateGraph:
    nodes = nodes or OrchestrationNodes()

    graph = StateGraph(OrchestrationState)

    graph.add_node("query_understanding", nodes.query_understanding)
    graph.add_node("weather", nodes.weather)
    graph.add_node("oceanographic", nodes.oceanographic)
    graph.add_node("gis", nodes.gis)
    graph.add_node("risk_suitability", nodes.risk_suitability)
    graph.add_node("safety_guard", nodes.safety_guard)
    graph.add_node("decision", nodes.decision)
    graph.add_node("route", nodes.route)
    graph.add_node("evidence", nodes.evidence)

    graph.add_edge(START, "query_understanding")

    graph.add_conditional_edges(
        "query_understanding",
        after_query_understanding,
        {"clarify": END, "weather": "weather", "oceanographic": "oceanographic", "gis": "gis"},
    )

    graph.add_edge("weather", "risk_suitability")
    graph.add_edge("oceanographic", "risk_suitability")
    graph.add_edge("gis", "risk_suitability")

    graph.add_edge("risk_suitability", "safety_guard")
    graph.add_edge("safety_guard", "decision")

    graph.add_conditional_edges("decision", after_decision, {"route": "route", "evidence": "evidence"})

    graph.add_edge("route", "evidence")
    graph.add_edge("evidence", END)

    return graph.compile()
