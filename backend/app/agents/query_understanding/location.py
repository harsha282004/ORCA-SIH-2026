"""Deterministic location resolution — Phase 5 task spec §11: "Do not allow
the LLM to silently invent precise coordinates... For known supported demo
region use existing configured spatial boundaries... Do not hardcode
arbitrary coordinates from the model output. Coordinate validation must
pass through existing GIS validation."

The LLM only ever supplies a free-text place name
(`RawIntentResult.location_name` — see models.py). This module maps that
name to a small, explicitly-curated set of known places within the
configured demo bbox (`app.fabric.spatial.validate_point` reused for
coordinate validation, not reimplemented), or signals that the name is
unrecognized so the agent can ask for clarification — it never silently
guesses a location outside the supported region.
"""
from __future__ import annotations

from app.fabric.spatial import validate_point
from app.models.geo import BBox

# Half-width buffer (degrees, ~3.3km) around each named place's reference
# point — NOT a claim of precise administrative boundaries, just enough to
# give a small, sensible candidate area for a demo-scale query.
_PLACE_BUFFER_DEG = 0.03

# A small, explicitly-curated gazetteer for the ONLY supported demo region
# (Mangaluru-Udupi coastal Karnataka, architecture.md §44) — not a general
# geocoder. Coordinates are approximate town-center reference points.
_KNOWN_PLACES: dict[str, tuple[float, float]] = {
    "mangaluru": (12.87, 74.85),
    "mangalore": (12.87, 74.85),  # common alternate spelling
    "udupi": (13.34, 74.75),
    "malpe": (13.35, 74.71),
    "ullal": (12.80, 74.86),
}


def resolve_location(location_name: str | None, *, demo_bbox: BBox) -> dict | None:
    """Returns architecture.md §12's `IntentResult.location` shape
    (`{type, name, resolved_bbox}`), or `None` if `location_name` was given
    but not recognized — the caller must treat `None` as "needs
    clarification", never fall through to a silent guess.

    An EMPTY/missing `location_name` resolves to the full configured demo
    region (`type="region"`) — a reasonable default for a general query
    that doesn't name a specific place, not a guess about which specific
    spot the user meant.
    """
    if not location_name:
        return {
            "type": "region",
            "name": "Mangaluru-Udupi coastal Karnataka",
            "resolved_bbox": demo_bbox.model_dump(),
        }

    key = location_name.strip().lower()
    if key not in _KNOWN_PLACES:
        return None

    latitude, longitude = _KNOWN_PLACES[key]
    validate_point(latitude, longitude)

    bbox = BBox(
        min_lat=max(demo_bbox.min_lat, latitude - _PLACE_BUFFER_DEG),
        min_lon=max(demo_bbox.min_lon, longitude - _PLACE_BUFFER_DEG),
        max_lat=min(demo_bbox.max_lat, latitude + _PLACE_BUFFER_DEG),
        max_lon=min(demo_bbox.max_lon, longitude + _PLACE_BUFFER_DEG),
    )
    return {"type": "named_place", "name": location_name, "resolved_bbox": bbox.model_dump()}
