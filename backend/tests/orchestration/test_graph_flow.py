"""End-to-end behavioral tests of the compiled orchestration graph —
categories C (LangGraph flow) and E-F (Safety Guard / Decision cannot be
bypassed) from the Phase 5 task spec. Offline: fake Weather/Oceanographic
agents, real (network-free) GIS agent, FakeLLMProvider throughout.
"""
from __future__ import annotations

from app.orchestration.graph import build_orchestration_graph
from app.orchestration.state import OrchestrationState
from tests.orchestration.conftest import (
    OPEN_WATER_LAT,
    OPEN_WATER_LON,
    build_nodes,
    make_marine_result,
    make_raw_intent,
    make_weather_result,
)

# Inside DEMO_LAND_FIXTURE (see tests/routing/test_api_route.py: lat 12.70-13.45, lon 74.80-75.05).
LAND_LOCATION_NAME = "Mangaluru"  # gazetteer coordinate (12.87, 74.85) falls inside the land fixture


def _run(nodes, query: str = "Is it safe to go fishing today?") -> OrchestrationState:
    graph = build_orchestration_graph(nodes)
    raw = graph.invoke(OrchestrationState(query=query))
    return OrchestrationState.model_validate(raw)


def test_happy_path_produces_a_recommend_decision_for_low_risk_open_water() -> None:
    nodes = build_nodes(
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
        marine_result=make_marine_result(wave_height=0.5),
    )
    final = _run(nodes)

    assert final.status == "completed"
    assert final.decision.outcome == "RECOMMEND"
    assert final.safety.outcome == "PASS"
    assert final.explanation is not None
    # Weather/Oceanographic/GIS run in parallel — their relative completion
    # order is not guaranteed, so only the SET of nodes that ran (and that
    # every one succeeded) is asserted, not a fixed order.
    assert {r.agent_name for r in final.agent_runs} == {
        "query_understanding", "gis", "oceanographic", "weather", "risk_suitability", "safety_guard", "decision", "evidence_explanation",
    }
    assert all(r.status == "ok" for r in final.agent_runs)


def test_ambiguous_location_short_circuits_before_any_data_agent_runs() -> None:
    nodes = build_nodes(raw_intent=make_raw_intent(location_name="Atlantis"))
    final = _run(nodes, query="Is it safe near Atlantis?")

    assert final.status == "clarification_needed"
    assert final.clarification is not None
    assert final.weather is None
    assert final.decision is None
    assert [r.agent_name for r in final.agent_runs] == ["query_understanding"]


def test_location_inside_a_hard_geofence_is_blocked_regardless_of_weather() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(location_name=LAND_LOCATION_NAME),
        weather_result=make_weather_result(wind_speed_10m=1.0, weathercode=0),  # deliberately mild — should not matter
        marine_result=make_marine_result(wave_height=0.1),
    )
    final = _run(nodes, query="Is it safe to fish near Mangaluru?")

    assert final.safety.outcome == "BLOCK_BOUNDARY"
    assert final.decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_weather_branch_failure_is_surfaced_as_missing_data_never_a_silent_pass() -> None:
    nodes = build_nodes(weather_result=make_weather_result(status="failed"))
    final = _run(nodes)

    assert final.safety.outcome == "BLOCK_MISSING_DATA"
    assert final.decision.outcome == "NO_SAFE_RECOMMENDATION"
    assert final.status == "completed"  # the graph still completes structurally — it does not crash


def test_marine_branch_failure_is_also_surfaced_as_missing_data() -> None:
    nodes = build_nodes(marine_result=make_marine_result(status="failed"))
    final = _run(nodes)

    assert final.safety.outcome == "BLOCK_MISSING_DATA"
    assert final.decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_route_is_skipped_when_not_requested() -> None:
    nodes = build_nodes(raw_intent=make_raw_intent(requires_route=False))
    final = _run(nodes)

    assert final.route_note is None
    assert "route" not in [r.agent_name for r in final.agent_runs]


def test_route_conditional_branch_runs_when_requested_and_safety_passes() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(requires_route=True),
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
        marine_result=make_marine_result(wave_height=0.5),
    )
    final = _run(nodes)

    assert final.safety.outcome == "PASS"
    assert final.route_note is not None
    assert "route" in [r.agent_name for r in final.agent_runs]


def test_route_is_never_attempted_when_safety_blocks_even_if_requested() -> None:
    nodes = build_nodes(
        raw_intent=make_raw_intent(location_name=LAND_LOCATION_NAME, requires_route=True),
    )
    final = _run(nodes, query="Route me safely near Mangaluru")

    assert final.safety.outcome == "BLOCK_BOUNDARY"
    assert final.route_note is None
    assert "route" not in [r.agent_name for r in final.agent_runs]


def test_llm_cannot_make_the_decision_engine_recommend_a_blocked_query() -> None:
    """Even if the Explanation LLM is instructed (via a hostile fake
    response) to write reassuring prose, the DECISION itself — computed
    entirely before the LLM is ever invoked — must remain
    NO_SAFE_RECOMMENDATION. The LLM has no code path to influence it.
    """
    nodes = build_nodes(
        raw_intent=make_raw_intent(location_name=LAND_LOCATION_NAME),
        explanation_rationale="It is completely safe to go ahead and fish here.",
    )
    final = _run(nodes, query="Is it safe near Mangaluru?")

    assert final.decision.outcome == "NO_SAFE_RECOMMENDATION"
    # ...and the grounding/safety-claim check rejects the LLM's unsafe
    # claim, falling back to the deterministic template instead.
    assert final.explanation.used_fallback_template is True
    assert "is safe" not in final.explanation.rationale.lower()


def test_repeated_invocation_with_identical_inputs_is_deterministic() -> None:
    nodes = build_nodes(
        weather_result=make_weather_result(wind_speed_10m=3.0, weathercode=0),
        marine_result=make_marine_result(wave_height=0.5),
    )
    first = _run(nodes)
    second = _run(nodes)

    assert first.decision.outcome == second.decision.outcome
    assert first.decision.risk_score == second.decision.risk_score
    assert first.safety.outcome == second.safety.outcome
