"""Deterministic edge cost — architecture.md §26:

    edge_cost = distance_cost + environmental_risk_cost + hazard_cost + geofence_cost

Risk and hazard costs scale with the distance actually traveled through a
cell (the same pattern the architecture's own cited precedent, VISIR-2,
uses for weather-routing edge costs — architecture.md §26 "Grounding") so
a long stretch through moderately risky water costs more than a brief one,
and the units of every term stay comparable ("cost-km").

This module never recomputes risk/hazard itself — it only consumes
`RoutingNode.risk_score` / `.hazard_score` / `.geofence_soft_penalty`,
which are populated by Phase 2's own Risk Engine components
(app.routing.grid.build_routing_grid).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.gis.distance import haversine_km
from app.routing.config import RoutingCostWeights
from app.routing.grid import RoutingNode


class EdgeCostBreakdown(BaseModel):
    distance_km: float
    distance_cost: float
    environmental_risk_cost: float
    hazard_cost: float
    geofence_cost: float
    total: float


def compute_edge_cost(from_node: RoutingNode, to_node: RoutingNode, weights: RoutingCostWeights) -> EdgeCostBreakdown:
    distance_km = haversine_km(
        from_node.cell.centroid_lat, from_node.cell.centroid_lon, to_node.cell.centroid_lat, to_node.cell.centroid_lon
    )

    distance_cost = weights.distance * distance_km
    environmental_risk_cost = weights.environmental_risk * (to_node.risk_score or 0.0) * distance_km
    hazard_cost = weights.hazard * (to_node.hazard_score or 0.0) * distance_km
    geofence_cost = weights.geofence_soft * to_node.geofence_soft_penalty * distance_km

    total = distance_cost + environmental_risk_cost + hazard_cost + geofence_cost

    return EdgeCostBreakdown(
        distance_km=distance_km,
        distance_cost=distance_cost,
        environmental_risk_cost=environmental_risk_cost,
        hazard_cost=hazard_cost,
        geofence_cost=geofence_cost,
        total=total,
    )
