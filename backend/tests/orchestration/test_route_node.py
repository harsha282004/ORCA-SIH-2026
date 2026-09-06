"""LangGraph `route` node — Phase 5 task §28's "Ask ORCA Routing" workflow:

    User -> Query Understanding -> LangGraph -> Route Agent ->
    deterministic route generation -> Risk -> Hazards -> Safety ->
    Route ranking -> Evidence -> Groq explanation

Offline throughout: `FakeEnvironmentalProvider` (no live HTTP), the real
(network-free, fixture-only) GIS agent, `FakeHazardCache` (no live GDACS) —
matching this package's own "no real network" contract.
"""
from __future__ import annotations

from app.orchestration.graph import build_orchestration_graph
from app.orchestration.state import OrchestrationState
from app.routing.config import GridConfig, RoutingConfig, RoutingCostWeights, SearchConfig
from tests.orchestration.conftest import build_nodes, make_raw_intent

# Same 3km/20000-cell defaults as routing_config.yaml, but constructed
# directly here so this test package never depends on that file's content.
FAST_ROUTING_CONFIG = RoutingConfig(
    grid=GridConfig(resolution_km=3.0, max_cells=20000),
    search=SearchConfig(max_expanded_nodes=200000),
    cost_weights=RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0, alternative_penalty=8.0),
)


class FakeEnvironmentalProvider:
    """Mirrors tests/routing/test_api_route.py's own fake — no network, no
    Redis, a flat calm-conditions grid.
    """

    def __init__(self, *, gis_agent, requested_time, risk_config):
        del gis_agent, requested_time, risk_config
        self.overall_temporal_validity = "VALID"
        self.overall_confidence = 0.9
        self.used_synthetic_fallback = False

    def prepare(self, bbox) -> None:
        del bbox

    def risk_provider(self, cell) -> float:
        del cell
        return 0.05

    def hazard_provider(self, cell) -> float:
        del cell
        return 0.0


def _run(nodes, query: str) -> OrchestrationState:
    graph = build_orchestration_graph(nodes)
    raw = graph.invoke(OrchestrationState(query=query))
    return OrchestrationState.model_validate(raw)


def test_route_planning_with_two_resolvable_places_computes_a_real_route() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(intent_class="route_planning", destination_name="Udupi", requires_route=True),
        environmental_provider_class=FakeEnvironmentalProvider,
        routing_config=FAST_ROUTING_CONFIG,
    )
    final = _run(nodes, query="Plan a route from Mangaluru to Udupi")

    assert final.status == "completed"
    assert final.route is not None
    assert final.route.metrics.total_distance_km > 0
    assert final.route_note is not None and "km" in final.route_note
    assert final.decision is not None
    assert final.decision.outcome in ("RECOMMEND", "RECOMMEND_WITH_CAUTION", "PROVIDE_ALTERNATIVES", "NO_SAFE_RECOMMENDATION")
    assert "route" in [r.agent_name for r in final.agent_runs]


def test_route_planning_without_a_named_destination_falls_back_to_the_honest_note() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(intent_class="route_planning", requires_route=True),  # no destination_name
        environmental_provider_class=FakeEnvironmentalProvider,
        routing_config=FAST_ROUTING_CONFIG,
    )
    final = _run(nodes, query="Plan a route near Mangaluru")

    assert final.route is None
    assert final.route_note is not None
    assert "resolvable destination" in final.route_note or "Plan a route" in final.route_note


def test_calm_route_recommends_and_carries_no_critical_hazard() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(intent_class="route_planning", destination_name="Udupi", requires_route=True),
        environmental_provider_class=FakeEnvironmentalProvider,
        routing_config=FAST_ROUTING_CONFIG,
    )
    final = _run(nodes, query="Plan a safe route from Mangaluru to Udupi")

    assert final.decision.outcome == "RECOMMEND"
    assert final.safety.outcome == "PASS"
    assert all(h.severity not in ("DANGER", "CRITICAL") for h in final.route_hazards)


def test_route_decision_overrides_the_origin_point_decision_for_this_query() -> None:
    """The route's OWN decision — not the origin point's — is what a
    route_planning query's final `decision` field must reflect (task §28's
    "Route ranking" step is the thing being explained, not the origin's
    standalone safety_check)."""
    nodes = build_nodes(
        raw_intent=make_raw_intent(intent_class="route_planning", destination_name="Udupi", requires_route=True),
        environmental_provider_class=FakeEnvironmentalProvider,
        routing_config=FAST_ROUTING_CONFIG,
    )
    final = _run(nodes, query="Plan a route from Mangaluru to Udupi")

    assert final.decision.risk_score == (final.route.metrics.max_risk_score or 0.0)


def test_deterministic_repeatability_of_route_node() -> None:
    def run_once():
        nodes = build_nodes(
            raw_intent=make_raw_intent(intent_class="route_planning", destination_name="Udupi", requires_route=True),
            environmental_provider_class=FakeEnvironmentalProvider,
            routing_config=FAST_ROUTING_CONFIG,
        )
        return _run(nodes, query="Plan a route from Mangaluru to Udupi")

    a, b = run_once(), run_once()
    assert a.route.metrics.total_distance_km == b.route.metrics.total_distance_km
    assert a.decision.outcome == b.decision.outcome
