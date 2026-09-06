"""INCOIS chlorophyll/SST WMS client — Phase 1 Marine Data Foundation.

Source: ESSO-INCOIS (Indian National Centre for Ocean Information
Services), the same organization that operates the official PFZ (Potential
Fishing Zone) advisory. This module talks to INCOIS's own public GeoServer
instance backing their PFZ WebGIS (https://incois.gov.in/geoportal/MFASPFZ/
index.html), verified live during this task at
https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/ — no API key, no
authentication.

Investigation summary (see docs/PHASE_1_MARINE_DATA_FOUNDATION_REPORT.md
for the full record): this GeoServer instance's WFS GetCapabilities
returns an EMPTY FeatureTypeList (verified) — there is no vector/polygon
PFZ layer exposed here or on the sibling `incois.gov.in/gisserver/PFZ/`
host (which 404s). What IS real and live is two WMS COVERAGE layers in
this workspace: `chl` ("Chlorophyll Concentration") and `sst` ("Sea
Surface Temperature") — the two satellite-derived inputs INCOIS's own PFZ
methodology is built from. Both support `GetFeatureInfo`, verified to
return real single-band pixel values (not styled RGB) at a point inside
the ORCA bbox. No WMS `time` dimension is advertised by either layer's
GetCapabilities entry, so this service exposes only INCOIS's current
operational raster — never a historical archive.

Units: INCOIS's GeoServer does not publish a machine-readable units field
on these layers (GetFeatureInfo returns a bare `GRAY_INDEX` number). Units
below (mg/m^3 for chlorophyll-a, degC for SST) are inferred from the
observed value ranges (0.1-2 mg/m^3 and ~28-31 degC are exactly the
expected ranges for this region/season) and from INCOIS's own published
PFZ methodology description, which states SST/chlorophyll are used in
these conventional units — NOT independently confirmed via service
metadata. This inference is documented, never hidden.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import httpx

INCOIS_WMS_BASE_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
INCOIS_SOURCE_URL = "https://incois.gov.in/geoportal/MFASPFZ/index.html"
INCOIS_PROVIDER = "ESSO-INCOIS (Indian National Centre for Ocean Information Services)"

Parameter = Literal["chl", "sst"]
PARAMETER_LABELS: dict[Parameter, str] = {"chl": "Chlorophyll Concentration", "sst": "Sea Surface Temperature"}
PARAMETER_UNITS: dict[Parameter, str] = {"chl": "mg/m^3", "sst": "degC"}

# INCOIS's GeoServer publishes no machine-readable NODATA/missing-value
# code for these coverages (verified: GetFeatureInfo's GRAY_INDEX carries
# no accompanying "this pixel is masked" flag). Live querying (this task)
# found land/masked pixels near the coast returning -1.0 for `sst` — never
# a physically real Arabian Sea sea-surface temperature — so this is
# treated as that layer's de facto NODATA sentinel. This is a DOCUMENTED
# INFERENCE from observed behavior, not an INCOIS-published spec; a broad
# physical-plausibility range serves the same "reject the sentinel, keep
# the real reading" purpose for `chl`.
_PLAUSIBLE_RANGE: dict[Parameter, tuple[float, float]] = {"sst": (0.0, 45.0), "chl": (0.0, 100.0)}

_VALUE_RE = re.compile(r'"GRAY_INDEX"\s*:\s*(-?[0-9.eE+-]+)')


class IncoisWmsError(Exception):
    """Raised on a genuine transport/HTTP failure — never silently becomes a fabricated value."""


@dataclass
class IncoisSample:
    parameter: Parameter
    latitude: float
    longitude: float
    value: float | None
    unit: str
    retrieved_at: datetime


def fetch_sample(*, parameter: Parameter, latitude: float, longitude: float, timeout_seconds: float = 15.0) -> IncoisSample:
    half = 0.02
    bbox = f"{longitude - half},{latitude - half},{longitude + half},{latitude + half}"
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": parameter,
        "QUERY_LAYERS": parameter,
        "SRS": "EPSG:4326",
        "BBOX": bbox,
        "WIDTH": "3",
        "HEIGHT": "3",
        "X": "1",
        "Y": "1",
        "INFO_FORMAT": "application/json",
        "FEATURE_COUNT": "1",
    }
    retrieved_at = datetime.now(timezone.utc)
    try:
        response = httpx.get(INCOIS_WMS_BASE_URL, params=params, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise IncoisWmsError(f"INCOIS WMS request failed: {exc}") from exc
    if response.status_code >= 400:
        raise IncoisWmsError(f"INCOIS WMS returned HTTP {response.status_code}: {response.text[:300]}")

    match = _VALUE_RE.search(response.text)
    value = float(match.group(1)) if match else None
    if value is not None:
        low, high = _PLAUSIBLE_RANGE[parameter]
        if not (low <= value <= high):
            value = None  # a masked/land-pixel sentinel, not a real reading — see module-level comment
    return IncoisSample(parameter=parameter, latitude=latitude, longitude=longitude, value=value, unit=PARAMETER_UNITS[parameter], retrieved_at=retrieved_at)


def fetch_sample_grid(
    *,
    parameter: Parameter,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    samples_per_axis: int,
    max_concurrent_requests: int = 6,
    timeout_seconds: float = 15.0,
) -> list[IncoisSample]:
    if samples_per_axis < 1:
        raise ValueError(f"samples_per_axis must be >= 1, got {samples_per_axis}")

    lat_step = (max_lat - min_lat) / samples_per_axis
    lon_step = (max_lon - min_lon) / samples_per_axis
    points: list[tuple[float, float]] = []
    for i in range(samples_per_axis):
        lat = min_lat + (i + 0.5) * lat_step
        for j in range(samples_per_axis):
            lon = min_lon + (j + 0.5) * lon_step
            points.append((lat, lon))

    def fetch(point: tuple[float, float]) -> IncoisSample:
        lat, lon = point
        return fetch_sample(parameter=parameter, latitude=lat, longitude=lon, timeout_seconds=timeout_seconds)

    max_workers = max(1, min(max_concurrent_requests, len(points)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, sorted(points)))


def fetch_reference_map_png(*, parameter: Parameter, min_lat: float, min_lon: float, max_lat: float, max_lon: float, width: int = 1024, height: int = 1024, timeout_seconds: float = 20.0) -> bytes:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.0",
        "REQUEST": "GetMap",
        "LAYERS": parameter,
        "SRS": "EPSG:4326",
        "BBOX": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
    }
    try:
        response = httpx.get(INCOIS_WMS_BASE_URL, params=params, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise IncoisWmsError(f"INCOIS WMS GetMap failed: {exc}") from exc
    if response.status_code >= 400 or not response.content.startswith(b"\x89PNG"):
        raise IncoisWmsError(f"INCOIS WMS GetMap did not return a PNG (HTTP {response.status_code})")
    return response.content
