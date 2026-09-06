"""Deterministic route comparison — Phase 5 task §14."""
from __future__ import annotations

from app.decision.models import Decision
from app.policy.models import SafetyGuardResult
from app.routing.comparison import compare_routes
from app.routing.models import Coordinate, RankedRoute, RouteMetrics, RouteResult


def _route_result(*, distance_km: float, max_risk: float) -> RouteResult:
    return RouteResult(
        origin=Coordinate(latitude=12.0, longitude=74.0),
        destination=Coordinate(latitude=12.1, longitude=74.1),
        path_coordinates=[Coordinate(latitude=12.0, longitude=74.0), Coordinate(latitude=12.1, longitude=74.1)],
        path_cells=[],
        metrics=RouteMetrics(
            total_distance_km=distance_km, distance_cost=distance_km, environmental_risk_cost=0.0, hazard_cost=0.0,
            geofence_cost=0.0, total_cost=distance_km, cell_count=2, average_risk_score=max_risk, max_risk_score=max_risk,
        ),
        grid_resolution_km=3.0, mode="demo", data_quality="fixture", temporal_validity="VALID", confidence=0.9,
    )


def _ranked(label: str, *, distance_km: float, risk_level: str, risk_score: float, outcome: str, safety_outcome: str = "PASS") -> RankedRoute:
    return RankedRoute(
        label=label,
        route=_route_result(distance_km=distance_km, max_risk=risk_score),
        risk_level=risk_level,
        decision=Decision(
            outcome=outcome, risk_level=risk_level, risk_score=risk_score, confidence=0.9,
            safety_guard_outcome=safety_outcome, reason=f"test reason for {outcome}",
        ),
        safety=SafetyGuardResult(outcome=safety_outcome, reason="test", triggered_rule="test"),
        hazards_near_route=[],
        hazard_source_tier="cached",
    )


def test_lower_risk_beats_shorter_distance() -> None:
    """Task §6/§14's own worked example: Route A (longer, LOW risk) must
    beat Route B (shorter, MODERATE risk)."""
    route_a = _ranked("A", distance_km=62.0, risk_level="LOW", risk_score=0.1, outcome="RECOMMEND")
    route_b = _ranked("B", distance_km=58.0, risk_level="MODERATE", risk_score=0.5, outcome="RECOMMEND_WITH_CAUTION")

    result = compare_routes([route_a, route_b])

    assert result.recommended_label == "A"
    assert "Route A" in result.reason
    assert "distance" in result.reason.lower()


def test_blocked_route_never_recommended_over_a_passing_one() -> None:
    route_a = _ranked("A", distance_km=90.0, risk_level="LOW", risk_score=0.1, outcome="RECOMMEND")
    route_b = _ranked("B", distance_km=40.0, risk_level="HIGH", risk_score=0.95, outcome="NO_SAFE_RECOMMENDATION", safety_outcome="BLOCK_HAZARD")

    result = compare_routes([route_a, route_b])

    assert result.recommended_label == "A"


def test_all_routes_blocked_recommends_none() -> None:
    route_a = _ranked("A", distance_km=90.0, risk_level="HIGH", risk_score=0.95, outcome="NO_SAFE_RECOMMENDATION", safety_outcome="BLOCK_HAZARD")
    route_b = _ranked("B", distance_km=40.0, risk_level="HIGH", risk_score=0.99, outcome="NO_SAFE_RECOMMENDATION", safety_outcome="BLOCK_HAZARD")

    result = compare_routes([route_a, route_b])

    assert result.recommended_label is None
    assert "none of the generated route options" in result.reason


def test_single_route_is_trivially_recommended() -> None:
    route_a = _ranked("A", distance_km=62.0, risk_level="LOW", risk_score=0.1, outcome="RECOMMEND")
    result = compare_routes([route_a])
    assert result.recommended_label == "A"


def test_empty_route_list_recommends_none_without_crashing() -> None:
    result = compare_routes([])
    assert result.recommended_label is None
    assert result.routes == []


def test_shorter_distance_only_breaks_ties_at_equal_risk() -> None:
    route_a = _ranked("A", distance_km=62.0, risk_level="LOW", risk_score=0.1, outcome="RECOMMEND")
    route_b = _ranked("B", distance_km=58.0, risk_level="LOW", risk_score=0.1, outcome="RECOMMEND")
    result = compare_routes([route_a, route_b])
    assert result.recommended_label == "B"  # same risk, shorter wins
