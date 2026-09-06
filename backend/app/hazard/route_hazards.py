"""Hazard-aware routing — Phase 4 task §19/20.

Reuses the EXISTING deterministic route computation
(`app.routing.engine.calculate_route`) and the EXISTING cyclone hazard feed
(`app.hazard.cyclone`) unchanged — this module adds NO new risk/cost
formula and does NOT touch A*/grid/costs (task's own "do not redesign the
existing route engine" instruction). It is a pure, additive, POST-HOC
check: given an already-computed route's `path_coordinates`, which REAL
active hazards fall within `RELEVANCE_RADIUS_KM` of ANY point on the path —
using the SAME haversine distance function every other ORCA GIS computation
uses, never an LLM judgment of "near."

Weather/wave/wind hazards are deliberately NOT duplicated here: the route's
own risk cost (`app.risk.components.wave_risk`/`wind_risk`, sampled along
the route by `app.agents.environmental_provider.AgentBackedEnvironmentalProvider`)
already penalizes exactly those conditions in the PATH CHOICE itself —
repeating them as a second "hazard near route" list would be a competing
signal for the same real data. Cyclone hazards are additive because
nothing in the existing A* cost function considers cyclone proximity at
all — a route can currently be "optimal" by wave/wind cost alone while
passing near an active storm system.
"""
from __future__ import annotations

from app.gis.distance import haversine_km
from app.hazard.cyclone import RELEVANCE_RADIUS_KM, fetch_active_cyclone_hazards
from app.hazard.models import Hazard
from app.routing.models import Coordinate


def hazards_near_route(path_coordinates: list[Coordinate], *, cache=None) -> tuple[list[Hazard], str]:
    """Returns (hazards, source_tier). `source_tier` is "live"/"cached"/
    "unavailable" (see `fetch_active_cyclone_hazards`) — a fetch failure is
    NEVER silently reported the same way as a genuine "no cyclone nearby"
    result; the caller (the route API) must surface `source_tier` alongside
    the (possibly empty) hazard list.
    """
    cyclones, tier = fetch_active_cyclone_hazards(cache=cache)
    if not cyclones or not path_coordinates:
        return [], tier

    relevant: list[Hazard] = []
    for hazard in cyclones:
        if hazard.latitude is None or hazard.longitude is None:
            continue
        min_distance = min(
            haversine_km(p.latitude, p.longitude, hazard.latitude, hazard.longitude) for p in path_coordinates
        )
        if min_distance <= RELEVANCE_RADIUS_KM:
            relevant.append(hazard.model_copy(update={"distance_km": round(min_distance, 1)}))

    relevant.sort(key=lambda h: h.distance_km if h.distance_km is not None else float("inf"))
    return relevant, tier
