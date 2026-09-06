"""Deterministic multi-turn reference resolution — architecture.md §31a
("Reference resolution boundary — LLM interprets, deterministic code
calculates").

The LLM's job stops at naming *what* the user is referring to
(`refers_to_prior`, `reference_type`, `reference_delta`). This module takes
that structured reference plus the PRIOR turn's already-resolved
`IntentResult` (from Conversation Session State) and performs the actual
geometry — the LLM never computes a coordinate, offset, or bbox itself:

    LLM interpretation (structured reference only)
            |
    Deterministic validation (schema + bounds check)
            |
    PostGIS-adjacent offset calculation (app.gis.distance.offset_point_km)
            |
    Re-enter the pipeline with the resolved IntentResult
"""
from __future__ import annotations

from app.agents.query_understanding.models import IntentResult
from app.fabric.spatial import validate_point
from app.gis.distance import offset_point_km
from app.models.geo import BBox

# Matches the half-width buffer app.agents.query_understanding.location
# uses for known-place lookups — an offset-derived point gets the same
# small, honestly-labeled candidate area, not a claim of precision.
_OFFSET_BUFFER_DEG = 0.03


def resolve_reference(
    intent: IntentResult,
    prior_intent: IntentResult | None,
    *,
    demo_bbox: BBox,
    prior_selected_point: dict | None = None,
) -> IntentResult:
    """Returns `intent`, possibly with its `location` replaced by a
    deterministically-computed one derived from `prior_intent` — never
    from anything the LLM supplied directly for the reference itself.

    A no-op (returns `intent` unchanged) whenever there is nothing to
    resolve: no prior turn, the current turn isn't flagged as a reference,
    or the reference doesn't carry a structured change this function knows
    how to apply. Never raises for an unresolvable reference — the caller
    proceeds with `intent` exactly as the (still deterministically
    resolved) location/time already stand.

    `prior_selected_point` (Phase 6, task §13/§18): a compact
    `{latitude, longitude, label, source}` dict — `app.session.models
    .SessionState.last_selected_point`, the actual coordinate of whatever
    ORCA most recently discussed (a top fishing candidate, a route
    endpoint, a safety-check point), which may be MORE specific than
    `prior_intent.location` (a whole named-place bbox). When a follow-up
    names no new place ("what about the waves there?", "is it still
    safe?"), anchoring to this exact point — then letting the SAME
    single-point pipeline re-run fully fresh — is what makes "is it still
    safe?" a genuine new evaluation rather than a replay of the old
    answer (task §15's "context is not authority").
    """
    if not intent.refers_to_prior or prior_intent is None:
        return intent

    if intent.reference_type == "same_query_different_param" and intent.reference_delta is not None:
        offshore_km = intent.reference_delta.offshore_distance_km
        if offshore_km is not None:
            offset_location = _offshore_offset_location(prior_intent, offshore_km, demo_bbox=demo_bbox)
            if offset_location is not None:
                return intent.model_copy(update={"location": offset_location})

    if (
        intent.reference_type in ("same_query_different_param", "follow_up_explanation")
        and intent.location.get("type") == "region"
    ):
        # Prefer the more specific point (the exact fishing candidate/route
        # endpoint most recently discussed) over the prior turn's whole
        # named-place bbox, when one is available.
        if prior_selected_point is not None:
            return intent.model_copy(update={"location": _point_to_location(prior_selected_point, demo_bbox=demo_bbox)})
        # A follow-up that names no specific place of its own ("why not the
        # zone further north?") stays anchored to the place the prior turn
        # was actually discussing, rather than silently falling back to the
        # full demo region (which `location.py` treats as the "no place
        # named" default — correct for a fresh query, wrong for a follow-up).
        if prior_intent.location.get("type") == "named_place":
            return intent.model_copy(update={"location": prior_intent.location})

    return intent


def _point_to_location(point: dict, *, demo_bbox: BBox) -> dict:
    latitude, longitude = point["latitude"], point["longitude"]
    bbox = BBox(
        min_lat=max(demo_bbox.min_lat, latitude - _OFFSET_BUFFER_DEG),
        min_lon=max(demo_bbox.min_lon, longitude - _OFFSET_BUFFER_DEG),
        max_lat=min(demo_bbox.max_lat, latitude + _OFFSET_BUFFER_DEG),
        max_lon=min(demo_bbox.max_lon, longitude + _OFFSET_BUFFER_DEG),
    )
    return {"type": "named_place", "name": point.get("label", "the previously discussed location"), "resolved_bbox": bbox.model_dump()}


def _offshore_offset_location(prior_intent: IntentResult, offshore_km: float, *, demo_bbox: BBox) -> dict | None:
    prior_bbox = prior_intent.location.get("resolved_bbox")
    if not prior_bbox:
        return None

    center_lat = (prior_bbox["min_lat"] + prior_bbox["max_lat"]) / 2
    center_lon = (prior_bbox["min_lon"] + prior_bbox["max_lon"]) / 2

    # "Offshore" is treated as due west for this specific coastline
    # (Mangaluru-Udupi runs roughly north-south, with open water to the
    # west) — a documented, scoped simplification, not a general
    # onshore/offshore solver for arbitrary coastlines.
    try:
        new_lat, new_lon = offset_point_km(center_lat, center_lon, west_km=offshore_km)
        validate_point(new_lat, new_lon)
    except ValueError:
        return None

    bbox = BBox(
        min_lat=max(demo_bbox.min_lat, new_lat - _OFFSET_BUFFER_DEG),
        min_lon=max(demo_bbox.min_lon, new_lon - _OFFSET_BUFFER_DEG),
        max_lat=min(demo_bbox.max_lat, new_lat + _OFFSET_BUFFER_DEG),
        max_lon=min(demo_bbox.max_lon, new_lon + _OFFSET_BUFFER_DEG),
    )
    prior_name = prior_intent.location.get("name", "the previous location")
    return {
        "type": "named_place",
        "name": f"{prior_name} (+{offshore_km:g} km offshore)",
        "resolved_bbox": bbox.model_dump(),
    }
