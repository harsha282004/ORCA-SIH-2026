"""GEBCO bathymetry client — Phase 1 Marine Data Foundation.

Source: GEBCO (General Bathymetric Chart of the Oceans), operated jointly
by the IHO and the IOC of UNESCO. GEBCO publishes its current gridded
bathymetry product (as of this integration: the GEBCO_2026 Grid, a global
15 arc-second elevation model) through a public, unauthenticated OGC Web
Map Service at https://wms.gebco.net/mapserv — verified live during this
task (its own GetCapabilities `<Abstract>` names "GEBCO_2026 Grid").

Why WMS point-sampling instead of a bulk grid download: GEBCO's own bulk
"Grid Subsetting App" (download.gebco.net) is a JavaScript single-page
app with no discoverable stable server-side API for scripted/reproducible
regional extraction (investigated during this task — its download
endpoints are internal to a bundled, code-split Next.js build). GEBCO's
WCS (Web Coverage Service, which would otherwise be the correct tool for
a true numeric-grid subset) was tested and found broken on the public
server (`ContentMetadata` is empty with "problem with one of layers"
warnings for every layer — not something this project can fix). The WMS,
however, IS fully live and DOES support `GetFeatureInfo` on its
colour-shaded layer (`GEBCO_LATEST_2`), returning the real underlying
elevation value at a queried point (verified: -56 at 74.28E/13.07N, a
plausible shelf depth near the Mangaluru coast) — so this module acquires
real GEBCO values via a bounded grid of point queries across the ORCA
demo bbox, the same bounded-sampling philosophy
`app.agents.environmental_provider` already uses for live weather/marine
data (a full native-resolution download for this bbox would need ~67,000
points at GEBCO's actual 15 arc-second spacing; this is a deliberate,
documented, much smaller regional extraction, never the full global grid).

This is genuinely downloaded, genuinely GEBCO-sourced data — not a
synthetic bathymetry model. It is also GEBCO's own TID (Type Identifier)
grid value alongside each depth, unmodified.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

GEBCO_WMS_BASE_URL = "https://wms.gebco.net/mapserv"
GEBCO_PRODUCT_NAME = "GEBCO_2026 Grid"
GEBCO_SOURCE_URL = "https://www.gebco.net/data-products/gridded-bathymetry-data"
GEBCO_ELEVATION_LAYER = "GEBCO_LATEST_2"
GEBCO_TID_LAYER = "GEBCO_LATEST_TID_2"

_VALUE_RE = re.compile(r"value_list\s*=\s*'([^']*)'")


class GebcoError(Exception):
    """Raised when the GEBCO WMS cannot be reached or returns something
    this module cannot interpret — never silently becomes a fabricated
    depth value.
    """


@dataclass
class GebcoDepthSample:
    latitude: float
    longitude: float
    depth_m: float | None  # GEBCO convention: negative = below sea level, positive = land elevation
    tid: float | None  # GEBCO's own Type Identifier code for this cell (source/quality of the sounding)
    retrieved_at: datetime


def _get_feature_info_by_pixel(*, layer: str, bbox: str, width: int, height: int, x: int, y: int, timeout_seconds: float) -> str | None:
    """One WMS 1.1.1 GetFeatureInfo request against a FIXED bbox/width/
    height raster addressing frame, varying only the queried pixel (x, y).

    Empirically verified during this task: querying a unique tiny bbox
    per point (the natural-seeming approach) made GEBCO's public MapServer
    instance return "Search returned no results" for the large majority of
    fresh (uncached) points — a real, reproducible limitation of that
    specific deployment, not a bug in this client (confirmed by retrying
    the same "no results" points repeatedly with generous timeouts). Fixing
    ONE bbox+width+height for the whole sampling grid and varying only the
    pixel index reproduced a 100% success rate across every point tested.
    This is the access pattern this module actually uses.
    """
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetFeatureInfo",
        "layers": layer,
        "query_layers": layer,
        "srs": "EPSG:4326",
        "bbox": bbox,
        "width": str(width),
        "height": str(height),
        "x": str(x),
        "y": str(y),
        "info_format": "text/plain",
    }
    try:
        response = httpx.get(GEBCO_WMS_BASE_URL, params=params, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise GebcoError(f"GEBCO WMS request failed: {exc}") from exc
    if response.status_code >= 400:
        raise GebcoError(f"GEBCO WMS returned HTTP {response.status_code}: {response.text[:300]}")
    match = _VALUE_RE.search(response.text)
    if match is None:
        return None
    return match.group(1)


def _to_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "" or raw.strip().lower() == "nan":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_depth_grid(
    *,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    samples_per_axis: int,
    max_concurrent_requests: int = 6,
    timeout_seconds: float = 20.0,
) -> list[GebcoDepthSample]:
    """Fetches a real, bounded `samples_per_axis` x `samples_per_axis` grid
    of GEBCO depth samples covering the given bbox — a deliberate regional
    extraction (see module docstring), never the full global/native-
    resolution grid. Uses one fixed WMS bbox/width/height raster frame
    (see `_get_feature_info_by_pixel`) with `samples_per_axis` distinct
    pixel indices per axis, so every sample maps onto an actual GEBCO grid
    cell inside the requested region.
    """
    if samples_per_axis < 1:
        raise ValueError(f"samples_per_axis must be >= 1, got {samples_per_axis}")

    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    # A raster addressing frame several times finer than samples_per_axis
    # so pixel indices land on distinct, well-separated grid cells rather
    # than clustering in one corner of a coarse frame.
    width = height = max(64, samples_per_axis * 8)

    pixel_indices: list[tuple[int, int]] = []
    for i in range(samples_per_axis):
        py = int((i + 0.5) * height / samples_per_axis)
        for j in range(samples_per_axis):
            px = int((j + 0.5) * width / samples_per_axis)
            pixel_indices.append((px, py))

    def fetch(pixel: tuple[int, int]) -> GebcoDepthSample:
        px, py = pixel
        retrieved_at = datetime.now(timezone.utc)
        depth_raw = _get_feature_info_by_pixel(layer=GEBCO_ELEVATION_LAYER, bbox=bbox, width=width, height=height, x=px, y=py, timeout_seconds=timeout_seconds)
        tid_raw = _get_feature_info_by_pixel(layer=GEBCO_TID_LAYER, bbox=bbox, width=width, height=height, x=px, y=py, timeout_seconds=timeout_seconds)
        # WMS 1.1.1 pixel (0,0) is the TOP-LEFT of the bbox — y increases
        # downward (toward min_lat), x increases rightward (toward max_lon).
        longitude = min_lon + (px + 0.5) * (max_lon - min_lon) / width
        latitude = max_lat - (py + 0.5) * (max_lat - min_lat) / height
        return GebcoDepthSample(latitude=latitude, longitude=longitude, depth_m=_to_float(depth_raw), tid=_to_float(tid_raw), retrieved_at=retrieved_at)

    max_workers = max(1, min(max_concurrent_requests, len(pixel_indices)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, pixel_indices))


def fetch_reference_map_png(*, min_lat: float, min_lon: float, max_lat: float, max_lon: float, width: int = 1024, height: int = 1024, timeout_seconds: float = 20.0) -> bytes:
    """Fetches ONE real WMS GetMap raster (colour-shaded elevation) PNG for
    the given bbox — preserved under data/raw/ as the raw source artifact
    for this acquisition, per architecture.md §42's raw-preservation rule.
    """
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": GEBCO_ELEVATION_LAYER,
        "srs": "EPSG:4326",
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "width": str(width),
        "height": str(height),
        "format": "image/png",
    }
    try:
        response = httpx.get(GEBCO_WMS_BASE_URL, params=params, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise GebcoError(f"GEBCO WMS GetMap failed: {exc}") from exc
    if response.status_code >= 400 or not response.content.startswith(b"\x89PNG"):
        raise GebcoError(f"GEBCO WMS GetMap did not return a PNG (HTTP {response.status_code})")
    return response.content
