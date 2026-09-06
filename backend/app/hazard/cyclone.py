"""Cyclone intelligence — Phase 4.

**Source audit result (see docs/PHASE_4_MARINE_SAFETY_HAZARD_INTELLIGENCE
_REPORT.md §3 for the full record):**

- `https://api.imd.gov.in/api/v1/cyclone_track` — IMD's own real,
  documented cyclone-track API. Tested live during this task:
  `HTTP 401 {"error":"API key missing"}`. It genuinely exists but requires
  an API key this deployment does not have and will not fabricate or
  bypass (architecture's own credential-handling rule). **UNAVAILABLE.**
- `https://www.nhc.noaa.gov/...` (NOAA NHC) — real, free, no key, but is
  the WRONG regional authority: NHC's basin is the Atlantic/Eastern
  Pacific, not the North Indian Ocean (Arabian Sea/Bay of Bengal) where
  ORCA's demo region sits. Using it would silently under-report cyclones
  in our region as "none" even during an active regional storm — worse
  than reporting UNAVAILABLE. **NOT USED.**
- `https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=TC`
  — the Global Disaster Alert and Coordination System (a UN OCHA/European
  Commission-supported humanitarian early-warning AGGREGATOR, not itself a
  meteorological authority). Tested live during this task: HTTP 200, real
  GeoJSON, `source` field names the actual issuing authority per event
  (e.g. "JTWC", "RSMC", "NOAA"), `iscurrent` flags genuinely active storms,
  covers ALL basins globally (verified: real Bay-of-Bengal 2025-season
  entries present in the same feed). **USED — clearly labeled as an
  aggregator of regional authorities, never claimed as a primary IMD/RSMC
  feed itself.**

No API key, no authentication. Cached via the existing `AgentCache`
(Redis, best-effort, never crashes the request on a cache/network miss) —
GDACS is a shared humanitarian resource; this deployment must not poll it
on every request (task's own "do not hammer external services" rule).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.agents.common.cache import AgentCache
from app.gis.distance import haversine_km
from app.hazard.models import Hazard

GDACS_BASE_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_SOURCE_URL = "https://www.gdacs.org/"
CYCLONE_CACHE_KEY = "orca:hazard:cyclone:active_tc"
CYCLONE_CACHE_TTL_SECONDS = 1800  # 30 min — matches the existing weather/marine cache TTL order of magnitude

# GDACS alertlevel -> ORCA HazardSeverity. GDACS's own three-color scale
# (Green/Orange/Red) is its documented public alert taxonomy; this is a
# direct, documented mapping onto Phase 4's severity vocabulary, not an
# invented equivalence.
_ALERT_LEVEL_SEVERITY = {"green": "ADVISORY", "orange": "WARNING", "red": "CRITICAL"}

# Cyclones farther than this from a query point are not considered
# "relevant" for that point's safety status — a documented, conservative
# distance (roughly a day's worth of typical tropical-cyclone translation
# speed plus a safety margin), not a scientifically derived radius of
# influence. Never silently omitted; the actual measured distance is
# always still reported for a cyclone found at ANY distance via
# `nearest_cyclone_distance_km`, this constant only gates `is_relevant`.
RELEVANCE_RADIUS_KM = 800.0


class CycloneSourceError(Exception):
    """Raised on a genuine transport/HTTP failure — never silently becomes an empty/fabricated result."""


def fetch_active_cyclones_raw(*, timeout_seconds: float = 15.0) -> list[dict]:
    """One real HTTP call to GDACS's own tropical-cyclone event list.
    Returns the raw GeoJSON features for events GDACS currently reports as
    active (`iscurrent == "true"`), globally — filtering to a specific
    region is the CALLER's job (deterministic, Shapely/haversine-based),
    never done by trusting an LLM's notion of "nearby."
    """
    try:
        response = httpx.get(GDACS_BASE_URL, params={"eventlist": "TC"}, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise CycloneSourceError(f"GDACS request failed: {exc}") from exc
    if response.status_code >= 400:
        raise CycloneSourceError(f"GDACS returned HTTP {response.status_code}: {response.text[:300]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise CycloneSourceError(f"GDACS returned non-JSON: {exc}") from exc

    features = payload.get("features", [])
    return [f for f in features if str(f.get("properties", {}).get("iscurrent", "")).lower() == "true"]


def _feature_to_hazard(feature: dict, retrieved_at: datetime) -> Hazard | None:
    props = feature.get("properties", {})
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates")
    if not coords or geometry.get("type") != "Point":
        return None  # a hazard we cannot deterministically locate is not reported as located

    alert_level = str(props.get("alertlevel", "")).lower()
    severity = _ALERT_LEVEL_SEVERITY.get(alert_level, "INFO")

    from_date = props.get("fromdate")
    to_date = props.get("todate")
    modified = props.get("datemodified")

    def _parse(dt: str | None) -> datetime | None:
        if not dt:
            return None
        try:
            return datetime.fromisoformat(dt).replace(tzinfo=timezone.utc) if "T" in dt else None
        except ValueError:
            return None

    return Hazard(
        hazard_type="CYCLONE",
        severity=severity,
        title=str(props.get("name") or props.get("eventname") or "Tropical Cyclone"),
        description=str(props.get("htmldescription") or props.get("description") or ""),
        latitude=coords[1],
        longitude=coords[0],
        valid_from=_parse(from_date),
        valid_until=_parse(to_date),
        observed_at=_parse(modified) or retrieved_at,
        source=f"GDACS (aggregating {props.get('source', 'regional meteorological authority')})",
        is_authoritative=True,  # GDACS republishes the ACTUAL issuing authority's bulletin, not its own assessment
        is_proxy=False,
        freshness="CURRENT",
        confidence=None,
    )


def fetch_active_cyclone_hazards(*, cache: AgentCache | None = None) -> tuple[list[Hazard], str]:
    """Returns (hazards, source_tier) where source_tier is "live" or
    "cached" — same vocabulary the rest of the project's data sources use.
    A cache/network failure returns an EMPTY list with source_tier
    "unavailable", never a fabricated "no cyclones" claim presented the
    same way as a genuine live check (see `CycloneAvailability` usage in
    app.hazard.engine).
    """
    now = datetime.now(timezone.utc)
    if cache is not None:
        cached = cache.get_json(CYCLONE_CACHE_KEY)
        if cached is not None:
            try:
                return [Hazard.model_validate(h) for h in cached], "cached"
            except Exception:  # noqa: BLE001 — a corrupted cache entry is a miss, never a crash
                pass

    try:
        features = fetch_active_cyclones_raw()
    except CycloneSourceError:
        return [], "unavailable"

    hazards = [h for f in features if (h := _feature_to_hazard(f, now)) is not None]

    if cache is not None:
        cache.set_json(CYCLONE_CACHE_KEY, [h.model_dump(mode="json") for h in hazards])

    return hazards, "live"


def relevant_cyclones(hazards: list[Hazard], *, latitude: float, longitude: float) -> list[Hazard]:
    """Deterministic spatial relevance (haversine — the SAME distance
    function every other ORCA GIS computation already uses, not a new
    formula) — never an LLM judgment of "nearby."
    """
    relevant = []
    for h in hazards:
        if h.latitude is None or h.longitude is None:
            continue
        distance = haversine_km(latitude, longitude, h.latitude, h.longitude)
        if distance <= RELEVANCE_RADIUS_KM:
            relevant.append(h.model_copy(update={"distance_km": round(distance, 1)}))
    return relevant
