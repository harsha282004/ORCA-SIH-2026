"""Structured routing errors — architecture.md §26: "No route found ...
returns a structured error — never a hallucinated or best-effort route."

Every failure mode in the routing pipeline is a distinct, typed exception
rather than a magic return value, so the API layer (backend/app/api/v1/route.py)
can map each one to an explicit error code without guessing.
"""
from __future__ import annotations

from app.routing.models import RouteValidationIssue


class RoutingError(Exception):
    """Base for all Phase 3 routing errors."""


class OriginValidationError(RoutingError):
    """Origin failed validation — A* is never run."""

    def __init__(self, issue: RouteValidationIssue):
        super().__init__(f"origin invalid: {issue.message}")
        self.issue = issue


class DestinationValidationError(RoutingError):
    """Destination failed validation — A* is never run."""

    def __init__(self, issue: RouteValidationIssue):
        super().__init__(f"destination invalid: {issue.message}")
        self.issue = issue


class RouteDataQualityError(RoutingError):
    """The environmental data backing this route's risk/hazard costs is not
    usable — stale, expired, missing, or below the configured minimum
    confidence (architecture.md §17 Temporal Validity Gate / §22 confidence,
    reused from Phase 1/2, not a new formula). Routing refuses rather than
    silently producing a confident-looking route on bad data.
    """

    def __init__(self, issue: RouteValidationIssue):
        super().__init__(f"environmental data not usable for routing: {issue.message}")
        self.issue = issue


class NoRouteFoundError(RoutingError):
    """A* exhausted the search space without reaching the destination."""

    def __init__(self, message: str, *, expanded_nodes: int):
        super().__init__(message)
        self.expanded_nodes = expanded_nodes


class RouteReconstructionError(RoutingError):
    """A* reported success but the reconstructed path failed the
    deterministic post-route validation pass (architecture.md Phase 3 spec
    §24) — an internal consistency bug, never a user input error, and never
    returned to the caller as if it were a valid route.
    """


class RoutingResourceLimitError(RoutingError):
    """The requested grid/search would exceed a configured resource safety
    limit (max grid cells or max A* expanded nodes). Raised before the
    unbounded work would actually happen — never a crash or a hang.
    """
