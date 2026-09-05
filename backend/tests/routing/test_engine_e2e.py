"""Phase 3 end-to-end deterministic routing chain (task spec §61):

    ROUTE REQUEST -> ORIGIN VALIDATION -> DESTINATION VALIDATION -> GRID
    -> LAND MASK -> GEOFENCE MASK -> RISK -> HAZARD -> EDGE COST -> A*
    -> PATH RECONSTRUCTION -> ROUTE VALIDATION -> ROUTE METRICS
    -> STRUCTURED RESPONSE

No LLM, no agent, no LangGraph anywhere in this chain. All fixture data.
"""
import pytest

from app.gis.geofence import Geofence, GeofenceCategory
from app.models.geo import BBox
from app.routing.config import RoutingConfig, GridConfig, SearchConfig, RoutingCostWeights
from app.routing.engine import calculate_route
from app.routing.errors import RoutingResourceLimitError
from app.routing.grid import zero_score_provider
from app.routing.models import Coordinate, RouteRequest

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)

LAND = Geofence(
    id="coast-fixture",
    name="coast-fixture",
    category=GeofenceCategory.LAND,
    is_authoritative=False,
    source="fixture",
    # Does not span the full latitude range — leaves a gap to route
    # around, unlike test_astar.py's FIXTURE D/F (which deliberately does
    # span the full range, to prove NO_ROUTE_FOUND when fully partitioned).
    geometry={
        "type": "Polygon",
        "coordinates": [[[74.15, 12.08], [74.20, 12.08], [74.20, 12.22], [74.15, 12.22], [74.15, 12.08]]],
    },
)


def test_full_chain_produces_structured_route() -> None:
    request = RouteRequest(
        origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28)
    )

    result = calculate_route(
        request,
        bbox=BBOX,
        geofences=[LAND],
        risk_provider=lambda cell: 0.1,
        hazard_provider=lambda cell: 0.0,
        temporal_validity="VALID",
        confidence=0.85,
        mode="demo",
        data_quality="fixture",
    )

    assert result.feasibility_status == "FEASIBLE"
    assert result.origin.latitude == 12.02
    assert result.destination.latitude == 12.28
    assert result.metrics.cell_count >= 2
    assert result.metrics.total_distance_km > 0
    assert result.metrics.total_cost >= result.metrics.distance_cost
    assert result.mode == "demo"
    assert result.data_quality == "fixture"
    assert result.temporal_validity == "VALID"
    assert result.confidence == 0.85
    assert "not an official maritime navigation recommendation" in result.disclaimer

    geojson = result.to_geojson_linestring()
    assert geojson["type"] == "LineString"
    assert len(geojson["coordinates"]) == result.metrics.cell_count


def test_full_chain_is_deterministic_end_to_end() -> None:
    request = RouteRequest(
        origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28)
    )
    kwargs = dict(
        bbox=BBOX,
        geofences=[LAND],
        risk_provider=lambda cell: 0.1,
        hazard_provider=lambda cell: 0.0,
        temporal_validity="VALID",
        confidence=0.85,
        mode="demo",
        data_quality="fixture",
    )

    results = [calculate_route(request, **kwargs) for _ in range(5)]
    distances = {r.metrics.total_distance_km for r in results}
    costs = {r.metrics.total_cost for r in results}
    cell_counts = {r.metrics.cell_count for r in results}
    paths = {tuple((c.row, c.col) for c in r.path_cells) for r in results}

    assert len(distances) == 1
    assert len(costs) == 1
    assert len(cell_counts) == 1
    assert len(paths) == 1


def test_grid_resource_limit_rejected_before_generation() -> None:
    tiny_max_cells_config = RoutingConfig(
        grid=GridConfig(resolution_km=3.0, max_cells=1),  # any real bbox needs more than 1 cell
        search=SearchConfig(max_expanded_nodes=1000),
        cost_weights=RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0),
    )
    request = RouteRequest(
        origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28)
    )

    with pytest.raises(RoutingResourceLimitError):
        calculate_route(
            request,
            bbox=BBOX,
            geofences=[],
            risk_provider=zero_score_provider,
            hazard_provider=zero_score_provider,
            temporal_validity="VALID",
            confidence=0.9,
            mode="demo",
            data_quality="fixture",
            routing_config=tiny_max_cells_config,
        )


def test_search_node_limit_rejected_during_astar() -> None:
    tiny_search_config = RoutingConfig(
        grid=GridConfig(resolution_km=3.0, max_cells=20000),
        search=SearchConfig(max_expanded_nodes=1),  # A* will exceed this almost immediately
        cost_weights=RoutingCostWeights(distance=1.0, environmental_risk=5.0, hazard=5.0, geofence_soft=3.0),
    )
    request = RouteRequest(
        origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28)
    )

    with pytest.raises(RoutingResourceLimitError):
        calculate_route(
            request,
            bbox=BBOX,
            geofences=[],
            risk_provider=zero_score_provider,
            hazard_provider=zero_score_provider,
            temporal_validity="VALID",
            confidence=0.9,
            mode="demo",
            data_quality="fixture",
            routing_config=tiny_search_config,
        )
