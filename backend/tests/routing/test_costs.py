import pytest

from app.gis.grid import GridCell
from app.routing.config import RoutingCostWeights
from app.routing.costs import compute_edge_cost
from app.routing.grid import RoutingNode
from shapely.geometry import Polygon

WEIGHTS = RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0)


def make_node(lat: float, lon: float, *, risk=None, hazard=None, geofence_soft=0.0) -> RoutingNode:
    cell = GridCell(
        cell_id=f"r0c0-{lat}-{lon}",
        row=0,
        col=0,
        geometry=Polygon([(lon, lat), (lon + 0.01, lat), (lon + 0.01, lat + 0.01), (lon, lat + 0.01)]),
        centroid_lat=lat,
        centroid_lon=lon,
    )
    return RoutingNode(cell=cell, navigable=True, risk_score=risk, hazard_score=hazard, geofence_soft_penalty=geofence_soft)


def test_edge_cost_pure_distance_when_no_risk_hazard_geofence() -> None:
    a = make_node(12.0, 74.0, risk=0.0, hazard=0.0)
    b = make_node(12.01, 74.0, risk=0.0, hazard=0.0)
    cost = compute_edge_cost(a, b, WEIGHTS)
    assert cost.total == pytest.approx(cost.distance_cost)
    assert cost.environmental_risk_cost == 0.0
    assert cost.hazard_cost == 0.0
    assert cost.geofence_cost == 0.0


def test_edge_cost_risk_scales_with_distance() -> None:
    a = make_node(12.0, 74.0, risk=0.0)
    b_near = make_node(12.001, 74.0, risk=1.0)
    b_far = make_node(12.01, 74.0, risk=1.0)
    cost_near = compute_edge_cost(a, b_near, WEIGHTS)
    cost_far = compute_edge_cost(a, b_far, WEIGHTS)
    assert cost_far.environmental_risk_cost > cost_near.environmental_risk_cost


def test_edge_cost_additive_four_terms() -> None:
    a = make_node(12.0, 74.0)
    b = make_node(12.005, 74.005, risk=0.4, hazard=0.2, geofence_soft=0.1)
    cost = compute_edge_cost(a, b, WEIGHTS)
    assert cost.total == pytest.approx(
        cost.distance_cost + cost.environmental_risk_cost + cost.hazard_cost + cost.geofence_cost
    )


def test_edge_cost_missing_risk_treated_as_none_not_penalized() -> None:
    a = make_node(12.0, 74.0)
    b = make_node(12.005, 74.0, risk=None, hazard=None)
    cost = compute_edge_cost(a, b, WEIGHTS)
    assert cost.environmental_risk_cost == 0.0
    assert cost.hazard_cost == 0.0


def test_edge_cost_deterministic() -> None:
    a = make_node(12.0, 74.0, risk=0.3)
    b = make_node(12.01, 74.02, risk=0.7, hazard=0.2, geofence_soft=0.1)
    results = {compute_edge_cost(a, b, WEIGHTS).total for _ in range(10)}
    assert len(results) == 1


def test_zero_distance_weight_rejected() -> None:
    with pytest.raises(ValueError):
        RoutingCostWeights(distance=0.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0)


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValueError):
        RoutingCostWeights(distance=1.0, environmental_risk=-1.0, hazard=5.0, geofence_soft=3.0)
