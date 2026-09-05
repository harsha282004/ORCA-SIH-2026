"""Routing validation — architecture.md §26's destination validation gate,
extended (by the Phase 3 task spec) to origin, plus the temporal/confidence
gate reused from Phase 1/2.

Origin and destination validation always run BEFORE A* — never as a
byproduct of the cost function, exactly as architecture.md §26 requires
("closing the edge case where a technically-reachable-but-illegal route
could otherwise be returned").
"""
from __future__ import annotations

from typing import Literal

from app.fabric.spatial import InvalidCoordinateError, validate_point
from app.gis.geofence import Geofence, evaluate_point_against_geofences
from app.models.contracts import TemporalValidityStatus
from app.models.geo import BBox
from app.routing.grid import RoutingNode
from app.routing.models import RouteValidationIssue
from datetime import datetime


def validate_routing_point(
    latitude: float,
    longitude: float,
    *,
    role: Literal["origin", "destination"],
    bbox: BBox,
    geofences: list[Geofence],
    at_time: datetime | None,
    containing_node: RoutingNode | None,
) -> RouteValidationIssue | None:
    """Returns None if the point is valid and traversable, else a structured
    issue. Checks, in order:

    1. Coordinate validity (already enforced by `Coordinate`'s own Pydantic
       validator at request-parsing time, re-checked here for callers that
       bypass that model).
    2. Inside the configured routing domain (the server's demo bbox — users
       do not control this directly, closing the resource-safety concern
       architecture.md Phase 3 task spec §57 raises).
    3. Point-level hard-geofence check (precise — architecture.md §25).
    4. Cell-level navigability of the grid cell the point falls into
       (consistent with what A* will actually search over — a coarse grid
       could otherwise disagree with the precise point check at a
       coastline edge).
    """
    try:
        validate_point(latitude, longitude)
    except InvalidCoordinateError as exc:
        return RouteValidationIssue(code="INVALID_COORDINATES", message=str(exc))

    if not bbox.contains(latitude, longitude):
        return RouteValidationIssue(
            code="OUT_OF_DOMAIN",
            message=f"{role} ({latitude}, {longitude}) is outside the configured routing domain",
            details={"bbox": bbox.model_dump()},
        )

    geofence_result = evaluate_point_against_geofences(latitude, longitude, geofences, at_time=at_time)
    if geofence_result.blocked:
        return RouteValidationIssue(
            code="BLOCKED_LAND_OR_GEOFENCE",
            message=geofence_result.reason or f"{role} falls inside a hard geofence",
            details={"matched_geofence_id": geofence_result.matched_geofence_id},
        )

    if containing_node is not None and not containing_node.navigable:
        return RouteValidationIssue(
            code="BLOCKED_LAND_OR_GEOFENCE",
            message=f"{role} falls inside a non-navigable grid cell ({containing_node.block_reason})",
            details={"cell_id": containing_node.cell_id},
        )

    return None


def validate_environmental_data_quality(
    temporal_validity: TemporalValidityStatus,
    confidence: float,
    *,
    min_confidence_threshold: float,
) -> RouteValidationIssue | None:
    """architecture.md §17 Temporal Validity Gate + §22 confidence, reused
    verbatim (no second formula) as a gate on whether routing may proceed
    at all. Stale/expired/missing-timestamp data, or confidence below the
    Risk Engine's own configured minimum, refuses rather than silently
    producing a route that looks just as confident as one backed by good data.
    """
    if temporal_validity == "STALE":
        return RouteValidationIssue(code="STALE_DATA", message="environmental data is stale for the requested time")
    if temporal_validity == "EXPIRED":
        return RouteValidationIssue(
            code="EXPIRED_DATA", message="environmental data has expired for the requested time"
        )
    if temporal_validity == "MISSING_TIMESTAMP":
        return RouteValidationIssue(code="MISSING_DATA", message="environmental data has no resolvable timestamp")
    if temporal_validity == "INVALID_TIMESTAMP":
        return RouteValidationIssue(
            code="INVALID_TIMESTAMP", message="environmental data has inconsistent timestamps"
        )

    if confidence < min_confidence_threshold:
        return RouteValidationIssue(
            code="LOW_CONFIDENCE",
            message=f"confidence {confidence:.3f} is below the configured minimum {min_confidence_threshold:.3f}",
        )

    return None


def validate_route_path(
    path: list[RoutingNode],
    *,
    origin_rc: tuple[int, int],
    destination_rc: tuple[int, int],
    total_distance_km: float,
    total_cost: float,
) -> None:
    """Deterministic post-reconstruction validation (architecture.md Phase 3
    task spec §24) — an internal bug-detection pass, not a user-input
    check (bad user input is already rejected earlier by
    `validate_routing_point`). Raises AssertionError on failure; the
    caller (routing/engine.py) wraps this into a typed
    RouteReconstructionError so this is never mistaken for a validation
    result the API should show a user.
    """
    if not path:
        raise AssertionError("reconstructed path is empty")

    if (path[0].row, path[0].col) != origin_rc:
        raise AssertionError(f"path does not start at origin cell {origin_rc}: starts at {(path[0].row, path[0].col)}")
    if (path[-1].row, path[-1].col) != destination_rc:
        raise AssertionError(
            f"path does not end at destination cell {destination_rc}: ends at {(path[-1].row, path[-1].col)}"
        )

    seen: set[tuple[int, int]] = set()
    for node in path:
        rc = (node.row, node.col)
        if rc in seen:
            raise AssertionError(f"path revisits cell {rc} — indicates an algorithmic bug")
        seen.add(rc)
        if not node.navigable:
            raise AssertionError(f"path crosses a non-navigable cell {rc} ({node.block_reason})")

    for prev, curr in zip(path, path[1:]):
        row_delta = abs(curr.row - prev.row)
        col_delta = abs(curr.col - prev.col)
        if row_delta > 1 or col_delta > 1 or (row_delta == 0 and col_delta == 0):
            raise AssertionError(
                f"path has a disconnected jump between {(prev.row, prev.col)} and {(curr.row, curr.col)}"
            )

    if origin_rc != destination_rc and total_distance_km <= 0:
        raise AssertionError(f"origin != destination but total_distance_km={total_distance_km}")

    if not (total_cost == total_cost and total_cost != float("inf")):  # NaN- and inf-safe check
        raise AssertionError(f"total_cost is not finite: {total_cost}")
