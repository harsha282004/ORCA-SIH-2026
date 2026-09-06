"""Route-level safety classification — Phase 5 task §9/§11/§13.

Reuses fixture patterns from tests/routing/test_engine_e2e.py; builds real
`RouteResult`s via `calculate_route`, then verifies `evaluate_route_safety`
reuses the EXISTING Safety Guard/Decision Engine correctly for route-shaped
inputs.
"""
from __future__ import annotations

from app.hazard.models import Hazard
from app.models.geo import BBox
from app.risk.config import get_risk_config
from app.routing.engine import calculate_route
from app.routing.models import Coordinate, RouteRequest
from app.routing.safety import evaluate_route_safety

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)


def _route(*, risk_score: float, confidence: float = 0.9):
    request = RouteRequest(
        origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28)
    )
    return calculate_route(
        request, bbox=BBOX, geofences=[], risk_provider=lambda cell: risk_score, hazard_provider=lambda cell: 0.0,
        temporal_validity="VALID", confidence=confidence, mode="demo", data_quality="fixture",
    )


def test_low_risk_route_with_no_hazards_recommends() -> None:
    route = _route(risk_score=0.05)
    decision, safety, risk_level = evaluate_route_safety(route, hazards_near_route=[], risk_config=get_risk_config())
    assert risk_level == "LOW"
    assert safety.outcome == "PASS"
    assert decision.outcome == "RECOMMEND"


def test_moderate_risk_route_recommends_with_caution() -> None:
    route = _route(risk_score=0.5)
    decision, safety, risk_level = evaluate_route_safety(route, hazards_near_route=[], risk_config=get_risk_config())
    assert risk_level == "MODERATE"
    assert decision.outcome == "RECOMMEND_WITH_CAUTION"


def test_high_risk_route_without_alternative_is_no_safe_recommendation() -> None:
    route = _route(risk_score=0.9)
    decision, safety, risk_level = evaluate_route_safety(
        route, hazards_near_route=[], risk_config=get_risk_config(), alternative_exists=False
    )
    assert risk_level == "HIGH"
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_high_risk_route_with_alternative_provides_alternatives() -> None:
    route = _route(risk_score=0.9)
    decision, _safety, _risk_level = evaluate_route_safety(
        route, hazards_near_route=[], risk_config=get_risk_config(), alternative_exists=True
    )
    assert decision.outcome == "PROVIDE_ALTERNATIVES"


def test_critical_hazard_near_route_blocks_even_when_risk_is_low() -> None:
    """Task's own worked example (§9/§18): a calm-weather route must still
    be blocked if a real, active DANGER/CRITICAL hazard (e.g. a cyclone) is
    near it — never overridden by an otherwise-low risk score.
    """
    route = _route(risk_score=0.05)
    cyclone = Hazard(hazard_type="CYCLONE", severity="CRITICAL", title="Test Cyclone", description="", source="GDACS (test)", is_authoritative=True)
    decision, safety, _risk_level = evaluate_route_safety(route, hazards_near_route=[cyclone], risk_config=get_risk_config())
    assert safety.outcome == "BLOCK_HAZARD"
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_advisory_severity_hazard_does_not_block() -> None:
    route = _route(risk_score=0.05)
    advisory = Hazard(hazard_type="CYCLONE", severity="ADVISORY", title="Distant system", description="", source="GDACS (test)", is_authoritative=True)
    decision, safety, _risk_level = evaluate_route_safety(route, hazards_near_route=[advisory], risk_config=get_risk_config())
    assert safety.outcome == "PASS"
    assert decision.outcome == "RECOMMEND"


def test_deterministic_repeatability() -> None:
    route = _route(risk_score=0.3)
    results = {
        evaluate_route_safety(route, hazards_near_route=[], risk_config=get_risk_config())[0].outcome for _ in range(5)
    }
    assert len(results) == 1
