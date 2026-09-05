"""Deterministic route calculation endpoint — architecture.md §26, §34
(`POST /route`). No LLM, no LangGraph, no LLM-driven agent — this endpoint
is a thin HTTP wrapper over `app.routing.engine.calculate_route`.

Phase 4 update: risk/hazard costs are now backed by the real Weather and
Oceanographic Intelligence Agents (bounded spatial sampling — see
`app.agents.environmental_provider`), not Phase 3's flat fixture
placeholder. Geofences still come from the GIS & Geofencing Agent's
fixture set (`app.agents.gis.agent.GISGeofencingAgent.get_geofences`) —
Phase 1 never acquired real coastline/WDPA/EEZ data.

Both the GIS agent and the environmental-provider class are resolved via
FastAPI dependency injection (`get_gis_agent`,
`get_environmental_provider_class`) specifically so tests can override
them with fast, offline fakes (`app.dependency_overrides`) — this endpoint
does real, bounded live HTTP calls by default (~10-15s measured, see
docs/data_agents.md §Performance), which the *unit*/regression test suite
must never depend on. Live-endpoint behavior itself is verified manually
(see the Phase 4 report) and can be re-verified by simply calling the
endpoint without any override.

Response shape loosely follows architecture.md §34's general envelope
(`{data, evidence?, confidence?, provenance?, errors?}`) — `evidence` and
`provenance` don't exist yet at the API layer (Phase 6+ concepts), so only
`data`, `confidence`, and `errors` are populated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.agents.environmental_provider import AgentBackedEnvironmentalProvider
from app.agents.gis.agent import GISGeofencingAgent
from app.config import get_settings
from app.risk.config import get_risk_config
from app.routing.engine import calculate_route
from app.routing.errors import (
    DestinationValidationError,
    NoRouteFoundError,
    OriginValidationError,
    RouteDataQualityError,
    RouteReconstructionError,
    RoutingResourceLimitError,
)
from app.routing.models import RouteRequest

router = APIRouter()


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_environmental_provider_class() -> type[AgentBackedEnvironmentalProvider]:
    return AgentBackedEnvironmentalProvider


class RouteErrorResponse(BaseModel):
    code: str
    message: str


class RouteAPIResponse(BaseModel):
    data: dict | None = None
    confidence: float | None = None
    errors: list[RouteErrorResponse] | None = None


@router.post("/route")
def create_route(
    request: RouteRequest,
    response: Response,
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    provider_class=Depends(get_environmental_provider_class),
) -> RouteAPIResponse:
    settings = get_settings()
    risk_config = get_risk_config()

    geofences, _geofence_metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)

    provider = provider_class(gis_agent=gis_agent, requested_time=request.requested_time, risk_config=risk_config)
    provider.prepare(settings.demo_bbox)

    try:
        result = calculate_route(
            request,
            bbox=settings.demo_bbox,
            geofences=geofences,
            risk_provider=provider.risk_provider,
            hazard_provider=provider.hazard_provider,
            temporal_validity=provider.overall_temporal_validity,
            confidence=provider.overall_confidence,
            mode=settings.orca_mode,
            # Independent of ORCA_MODE (session type) — reflects whether
            # any sample site actually fell back to synthetic/demo data,
            # never a fabricated "live" label (architecture.md §16a).
            data_quality="fixture" if provider.used_synthetic_fallback else "live",
            risk_config=risk_config,
        )
        return RouteAPIResponse(data=result.model_dump(mode="json"), confidence=result.confidence)

    except (OriginValidationError, DestinationValidationError, RouteDataQualityError) as exc:
        response.status_code = 422
        return RouteAPIResponse(errors=[RouteErrorResponse(code=exc.issue.code, message=exc.issue.message)])

    except NoRouteFoundError as exc:
        response.status_code = 422
        return RouteAPIResponse(errors=[RouteErrorResponse(code="NO_ROUTE_FOUND", message=str(exc))])

    except RoutingResourceLimitError as exc:
        response.status_code = 413
        return RouteAPIResponse(errors=[RouteErrorResponse(code="ROUTING_RESOURCE_LIMIT", message=str(exc))])

    except RouteReconstructionError as exc:
        response.status_code = 500
        return RouteAPIResponse(errors=[RouteErrorResponse(code="INTERNAL_ROUTE_ERROR", message=str(exc))])
