"""The deterministic routing engine — architecture.md §26, orchestrating
the full Phase 3 chain:

    ROUTE REQUEST -> DATA-QUALITY GATE -> GRID -> LAND/GEOFENCE MASK
    -> ORIGIN VALIDATION -> DESTINATION VALIDATION -> A*
    -> PATH RECONSTRUCTION -> ROUTE VALIDATION -> ROUTE METRICS
    -> STRUCTURED RouteResult

No LLM, no LangGraph, no agent anywhere in this module or anything it
calls. The grid must exist before origin/destination validation can check
cell-level navigability (see app.routing.validation), but origin and
destination are still always fully validated before A* ever runs — the
architectural requirement that matters (architecture.md §26).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from app.gis.geofence import Geofence
from app.gis.grid import grid_dimensions
from app.models.contracts import Mode, TemporalValidityStatus
from app.models.geo import BBox
from app.risk.config import RiskConfig, get_risk_config
from app.routing.astar import astar_search
from app.routing.config import RoutingConfig, get_routing_config
from app.routing.costs import EdgeCostBreakdown
from app.routing.errors import (
    DestinationValidationError,
    OriginValidationError,
    RouteDataQualityError,
    RouteReconstructionError,
    RoutingResourceLimitError,
)
from app.routing.grid import EnvironmentalScoreProvider, RoutingNode, build_routing_grid, locate_cell
from app.routing.models import Coordinate, RouteCellRef, RouteMetrics, RouteRequest, RouteResult
from app.routing.validation import validate_environmental_data_quality, validate_route_path, validate_routing_point

DataQuality = Literal["fixture", "live"]


def calculate_route(
    request: RouteRequest,
    *,
    bbox: BBox,
    geofences: list[Geofence],
    risk_provider: EnvironmentalScoreProvider,
    hazard_provider: EnvironmentalScoreProvider,
    temporal_validity: TemporalValidityStatus,
    confidence: float,
    mode: Mode,
    data_quality: DataQuality,
    routing_config: RoutingConfig | None = None,
    risk_config: RiskConfig | None = None,
    cell_penalties: dict[tuple[int, int], float] | None = None,
) -> RouteResult:
    """`cell_penalties` (Phase 5, optional, default None): a map of
    `(row, col) -> alternative_penalty` applied to the freshly-built grid
    before A* runs — the ONLY mechanism `app.routing.alternatives` uses to
    steer a re-run toward a genuinely different corridor (see
    `app.routing.costs`'s module docstring). `None`/`{}` reproduces every
    pre-Phase-5 call's exact behavior; this parameter is never populated by
    `POST /api/v1/route`'s own single-route path.
    """
    routing_config = routing_config or get_routing_config()
    risk_config = risk_config or get_risk_config()
    at_time = request.requested_time or datetime.now(timezone.utc)

    data_issue = validate_environmental_data_quality(
        temporal_validity, confidence, min_confidence_threshold=risk_config.safety.min_confidence_threshold
    )
    if data_issue is not None:
        raise RouteDataQualityError(data_issue)

    resolution_km = routing_config.grid.resolution_km
    dims = grid_dimensions(bbox, resolution_km=resolution_km)
    total_cells = dims.n_rows * dims.n_cols
    if total_cells > routing_config.grid.max_cells:
        raise RoutingResourceLimitError(
            f"grid would contain {total_cells} cells, exceeding the configured "
            f"max_cells={routing_config.grid.max_cells}"
        )

    nodes = build_routing_grid(
        bbox,
        resolution_km=resolution_km,
        geofences=geofences,
        risk_provider=risk_provider,
        hazard_provider=hazard_provider,
        at_time=at_time,
    )

    if cell_penalties:
        for rc, penalty in cell_penalties.items():
            node = nodes.get(rc)
            # A non-navigable cell (land/hard geofence) stays non-navigable —
            # penalizing it further is meaningless and never makes it
            # traversable (task §6/§16: hard constraints stay hard).
            if node is not None and node.navigable:
                nodes[rc] = node.model_copy(update={"alternative_penalty": penalty})

    origin_rc = locate_cell(
        bbox, resolution_km=resolution_km, latitude=request.origin.latitude, longitude=request.origin.longitude
    )
    destination_rc = locate_cell(
        bbox,
        resolution_km=resolution_km,
        latitude=request.destination.latitude,
        longitude=request.destination.longitude,
    )

    origin_issue = validate_routing_point(
        request.origin.latitude,
        request.origin.longitude,
        role="origin",
        bbox=bbox,
        geofences=geofences,
        at_time=at_time,
        containing_node=nodes.get(origin_rc),
    )
    if origin_issue is not None:
        raise OriginValidationError(origin_issue)

    destination_issue = validate_routing_point(
        request.destination.latitude,
        request.destination.longitude,
        role="destination",
        bbox=bbox,
        geofences=geofences,
        at_time=at_time,
        containing_node=nodes.get(destination_rc),
    )
    if destination_issue is not None:
        raise DestinationValidationError(destination_issue)

    if origin_rc == destination_rc:
        # architecture.md Phase 3 task spec §27: a valid zero-distance
        # route, no search needed — both points already passed validation.
        path = [nodes[origin_rc]]
        edge_costs: list[EdgeCostBreakdown] = []
        total_cost = 0.0
    else:
        result = astar_search(
            nodes,
            origin_rc,
            destination_rc,
            routing_config.cost_weights,
            max_expanded_nodes=routing_config.search.max_expanded_nodes,
        )
        path = result.path
        edge_costs = result.edge_costs
        total_cost = result.total_cost

        total_distance_km = sum(e.distance_km for e in edge_costs)
        try:
            validate_route_path(
                path,
                origin_rc=origin_rc,
                destination_rc=destination_rc,
                total_distance_km=total_distance_km,
                total_cost=total_cost,
            )
        except AssertionError as exc:
            raise RouteReconstructionError(str(exc)) from exc

    return _build_result(
        request=request,
        path=path,
        edge_costs=edge_costs,
        total_cost=total_cost,
        grid_resolution_km=resolution_km,
        mode=mode,
        data_quality=data_quality,
        temporal_validity=temporal_validity,
        confidence=confidence,
    )


def _build_result(
    *,
    request: RouteRequest,
    path: list[RoutingNode],
    edge_costs: list[EdgeCostBreakdown],
    total_cost: float,
    grid_resolution_km: float,
    mode: Mode,
    data_quality: DataQuality,
    temporal_validity: TemporalValidityStatus,
    confidence: float,
) -> RouteResult:
    path_cells = [
        RouteCellRef(
            cell_id=node.cell_id,
            row=node.row,
            col=node.col,
            latitude=node.cell.centroid_lat,
            longitude=node.cell.centroid_lon,
            risk_score=node.risk_score,
            hazard_score=node.hazard_score,
            geofence_soft_penalty=node.geofence_soft_penalty,
        )
        for node in path
    ]
    path_coordinates = [Coordinate(latitude=node.cell.centroid_lat, longitude=node.cell.centroid_lon) for node in path]

    risk_scores = [node.risk_score for node in path if node.risk_score is not None]

    metrics = RouteMetrics(
        total_distance_km=sum(e.distance_km for e in edge_costs),
        distance_cost=sum(e.distance_cost for e in edge_costs),
        environmental_risk_cost=sum(e.environmental_risk_cost for e in edge_costs),
        hazard_cost=sum(e.hazard_cost for e in edge_costs),
        geofence_cost=sum(e.geofence_cost for e in edge_costs),
        alternative_penalty_cost=sum(e.alternative_penalty_cost for e in edge_costs),
        total_cost=total_cost,
        cell_count=len(path),
        average_risk_score=(sum(risk_scores) / len(risk_scores)) if risk_scores else None,
        max_risk_score=max(risk_scores) if risk_scores else None,
    )

    return RouteResult(
        origin=request.origin,
        destination=request.destination,
        path_coordinates=path_coordinates,
        path_cells=path_cells,
        metrics=metrics,
        grid_resolution_km=grid_resolution_km,
        mode=mode,
        data_quality=data_quality,
        temporal_validity=temporal_validity,
        confidence=confidence,
    )
