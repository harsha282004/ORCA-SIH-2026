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
from app.hazard.route_hazards import hazards_near_route
from app.risk.config import get_risk_config
from app.routing.alternatives import generate_route_alternatives
from app.routing.comparison import compare_routes
from app.routing.errors import (
    DestinationValidationError,
    NoRouteFoundError,
    OriginValidationError,
    RouteDataQualityError,
    RouteReconstructionError,
    RoutingResourceLimitError,
)
from app.routing.models import RankedRoute, RouteRequest, RouteResult
from app.routing.safety import evaluate_route_safety

router = APIRouter()


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_environmental_provider_class() -> type[AgentBackedEnvironmentalProvider]:
    return AgentBackedEnvironmentalProvider


def get_hazard_cache():
    """Phase 4: the same Redis-backed `AgentCache` `app.api.v1.safety` and
    `app.fishing.engine` already use for the cyclone check — one real
    GDACS fetch per route request (or a cache hit), never a live call per
    route grid cell.
    """
    from app.agents.common.cache import AgentCache
    from app.services.cache import get_client as get_redis_client

    try:
        client = get_redis_client()
    except Exception:  # noqa: BLE001
        client = None
    return AgentCache(client, ttl_seconds=1800)


class RouteErrorResponse(BaseModel):
    code: str
    message: str


class RouteAPIResponse(BaseModel):
    data: dict | None = None
    confidence: float | None = None
    errors: list[RouteErrorResponse] | None = None
    # Phase 5 (task §12/§14) — always present (possibly empty/null), never
    # a shape-shifting response: `alternatives` is `[]` and `comparison` is
    # `null` whenever `max_alternatives<=1` or no distinct alternative was
    # found, so an existing caller reading only `data`/`confidence`/`errors`
    # is completely unaffected by this extension.
    alternatives: list[dict] | None = None
    comparison: dict | None = None


@router.post("/route")
def create_route(
    request: RouteRequest,
    response: Response,
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    provider_class=Depends(get_environmental_provider_class),
    hazard_cache=Depends(get_hazard_cache),
) -> RouteAPIResponse:
    settings = get_settings()
    risk_config = get_risk_config()

    geofences, _geofence_metadata = gis_agent.get_geofences(bbox=settings.demo_bbox)

    provider = provider_class(gis_agent=gis_agent, requested_time=request.requested_time, risk_config=risk_config)
    provider.prepare(settings.demo_bbox)

    try:
        # Phase 5 (task §12): a SINGLE call handles both the plain
        # single-route request (max_alternatives=1, the default — produces
        # the byte-identical route Phase 3/4 always returned, see
        # tests/routing/test_alternatives.py
        # ::test_first_alternative_is_identical_to_the_plain_calculate_route_result)
        # and the alternative-route request, reusing the SAME already-
        # prepared (one real environmental-sampling pass) risk/hazard
        # providers for every candidate — never a second live fetch per
        # alternative.
        routes: list[RouteResult] = generate_route_alternatives(
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
            max_alternatives=request.max_alternatives,
        )

        ranked_routes: list[RankedRoute] = []
        for index, route in enumerate(routes):
            label = chr(ord("A") + index)
            # Phase 4 §19/20: a real, additive hazard-proximity check
            # against THIS route's own computed path — never a second
            # routing/cost pass, and never a duplicate GDACS fetch (a
            # cache hit/miss is resolved once, reused for every route —
            # see app.hazard.cyclone.fetch_active_cyclone_hazards).
            hazards, hazard_source_tier = hazards_near_route(route.path_coordinates, cache=hazard_cache)
            decision, safety, risk_level = evaluate_route_safety(
                route, hazards_near_route=hazards, risk_config=risk_config, alternative_exists=len(routes) > 1
            )
            ranked_routes.append(
                RankedRoute(
                    label=label, route=route, risk_level=risk_level, decision=decision, safety=safety,
                    hazards_near_route=hazards, hazard_source_tier=hazard_source_tier,
                )
            )

        comparison = compare_routes(ranked_routes) if len(ranked_routes) > 1 else None

        primary = ranked_routes[0]
        data = primary.route.model_dump(mode="json")
        data["label"] = primary.label
        data["risk_level"] = primary.risk_level
        data["safety"] = primary.safety.model_dump(mode="json")
        data["decision"] = primary.decision.model_dump(mode="json")
        data["hazards_near_route"] = [h.model_dump(mode="json") for h in primary.hazards_near_route]
        data["hazard_source_tier"] = primary.hazard_source_tier

        alternatives_data = []
        for ranked in ranked_routes[1:]:
            alt = ranked.route.model_dump(mode="json")
            alt["label"] = ranked.label
            alt["risk_level"] = ranked.risk_level
            alt["safety"] = ranked.safety.model_dump(mode="json")
            alt["decision"] = ranked.decision.model_dump(mode="json")
            alt["hazards_near_route"] = [h.model_dump(mode="json") for h in ranked.hazards_near_route]
            alt["hazard_source_tier"] = ranked.hazard_source_tier
            alternatives_data.append(alt)

        return RouteAPIResponse(
            data=data,
            confidence=primary.route.confidence,
            alternatives=alternatives_data,
            comparison=comparison.model_dump(mode="json") if comparison is not None else None,
        )

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
