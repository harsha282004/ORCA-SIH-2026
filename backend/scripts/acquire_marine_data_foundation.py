"""Phase 1 — Marine Data Foundation acquisition script.

Acquires REAL data for the ORCA demo bbox from two live, unauthenticated,
public services investigated and verified during this task:

    1. GEBCO_2026 Grid bathymetry — https://wms.gebco.net/mapserv (WMS)
    2. INCOIS chlorophyll + SST     — https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms

No credentials, no API keys. Every value is a real HTTP response from the
provider named above — nothing here is synthesized. Run this script once
(or whenever a refresh is wanted); its output is what
`GET /api/v1/layers/bathymetry` and `GET /api/v1/layers/oceanography`
(chlorophyll) serve at runtime — the backend API never calls these
providers directly on a user request (bathymetry is static; INCOIS
chlorophyll/SST have no time dimension to poll per-request either).

Usage (from backend/, with the same Python environment the app runs in):
    python scripts/acquire_marine_data_foundation.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.data import gebco, incois_wms  # noqa: E402
from app.data.storage import create_tables, upsert_static_layer_source  # noqa: E402
from app.services.database import get_engine  # noqa: E402

# Matches `Settings.data_raw_dir`'s own documented convention: "data/raw"
# relative to the CURRENT WORKING DIRECTORY, not this script's location —
# run from the repo root on the host, or from /app inside the container
# (both now resolve to the same physical directory via the `./data:/app/data`
# volume mount in docker-compose.yml).
REPO_ROOT = Path.cwd()
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

GEBCO_SAMPLES_PER_AXIS = 15  # 225 real point samples — see app.data.gebco module docstring
INCOIS_SAMPLES_PER_AXIS = 8  # 64 real point samples per parameter — coarser, gentler on INCOIS's server


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path.stat().st_size


def _write_json(path: Path, obj: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2)
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def acquire_gebco(bbox, now: datetime) -> dict:
    print(f"\n=== GEBCO bathymetry — {gebco.GEBCO_PRODUCT_NAME} ===")
    print(f"Source: {gebco.GEBCO_WMS_BASE_URL}")
    print(f"Sampling {GEBCO_SAMPLES_PER_AXIS}x{GEBCO_SAMPLES_PER_AXIS} = {GEBCO_SAMPLES_PER_AXIS**2} real points over the ORCA bbox...")

    samples = gebco.fetch_depth_grid(
        min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon,
        samples_per_axis=GEBCO_SAMPLES_PER_AXIS,
    )
    valid = [s for s in samples if s.depth_m is not None]
    print(f"Received {len(samples)} responses, {len(valid)} with a real depth value.")

    raw_payload = {
        "source": "gebco-wms",
        "request_url": gebco.GEBCO_WMS_BASE_URL,
        "layer": gebco.GEBCO_ELEVATION_LAYER,
        "retrieved_at": now.isoformat(),
        "samples": [
            {"latitude": s.latitude, "longitude": s.longitude, "depth_m": s.depth_m, "tid": s.tid, "retrieved_at": s.retrieved_at.isoformat()}
            for s in samples
        ],
    }
    raw_path = RAW_DIR / "gebco" / f"gebco_2026_depth_samples_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    raw_size = _write_json(raw_path, raw_payload)
    raw_checksum = _sha256(raw_path.read_bytes())
    print(f"Raw samples saved: {raw_path.relative_to(REPO_ROOT)} ({raw_size:,} bytes)")

    print("Fetching one real WMS GetMap reference image...")
    png_bytes = gebco.fetch_reference_map_png(min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon)
    png_path = RAW_DIR / "gebco" / f"gebco_2026_reference_map_{now.strftime('%Y%m%dT%H%M%SZ')}.png"
    png_size = _write_bytes(png_path, png_bytes)
    png_checksum = _sha256(png_bytes)
    print(f"Raw reference PNG saved: {png_path.relative_to(REPO_ROOT)} ({png_size:,} bytes)")

    features = [
        {
            "type": "Feature",
            "properties": {"depth_m": s.depth_m, "tid": s.tid},
            "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
        }
        for s in valid
    ]
    processed = {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "dataset": gebco.GEBCO_PRODUCT_NAME,
            "provider": "GEBCO Compilation Group (IHO/IOC UNESCO)",
            "source_url": gebco.GEBCO_SOURCE_URL,
            "access_method": f"OGC WMS GetFeatureInfo, layer {gebco.GEBCO_ELEVATION_LAYER!r}, {gebco.GEBCO_WMS_BASE_URL}",
            "acquired_at": now.isoformat(),
            "crs": "EPSG:4326",
            "depth_convention": "negative = below sea level (bathymetry), positive = land elevation, meters",
            "bbox": {"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon},
            "grid_resolution": f"{GEBCO_SAMPLES_PER_AXIS}x{GEBCO_SAMPLES_PER_AXIS} bounded point samples (NOT the native 15 arc-second grid)",
            "sample_count_requested": len(samples),
            "sample_count_with_value": len(valid),
            "authoritative": True,
            "classification": "static",
        },
    }
    processed_path = PROCESSED_DIR / "gebco_bathymetry_orca_bbox.geojson"
    processed_size = _write_json(processed_path, processed)
    processed_checksum = _sha256(processed_path.read_bytes())
    print(f"Processed artifact saved: {processed_path.relative_to(REPO_ROOT)} ({processed_size:,} bytes)")

    return {
        "raw_path": str(raw_path.relative_to(REPO_ROOT)), "raw_size_bytes": raw_size, "raw_checksum_sha256": raw_checksum,
        "reference_png_path": str(png_path.relative_to(REPO_ROOT)), "reference_png_size_bytes": png_size, "reference_png_checksum_sha256": png_checksum,
        "processed_path": str(processed_path.relative_to(REPO_ROOT)), "processed_size_bytes": processed_size, "processed_checksum_sha256": processed_checksum,
        "sample_count_requested": len(samples), "sample_count_with_value": len(valid),
        "depth_min_m": min((s.depth_m for s in valid), default=None), "depth_max_m": max((s.depth_m for s in valid), default=None),
    }


def acquire_incois(parameter: str, label: str, bbox, now: datetime) -> dict:
    print(f"\n=== INCOIS {label} ({parameter}) ===")
    print(f"Source: {incois_wms.INCOIS_WMS_BASE_URL} (layer {parameter!r})")
    print(f"Sampling {INCOIS_SAMPLES_PER_AXIS}x{INCOIS_SAMPLES_PER_AXIS} = {INCOIS_SAMPLES_PER_AXIS**2} real points over the ORCA bbox...")

    samples = incois_wms.fetch_sample_grid(
        parameter=parameter, min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon,
        samples_per_axis=INCOIS_SAMPLES_PER_AXIS,
    )
    valid = [s for s in samples if s.value is not None]
    print(f"Received {len(samples)} responses, {len(valid)} with a real value.")

    raw_payload = {
        "source": f"incois-wms-{parameter}",
        "request_url": incois_wms.INCOIS_WMS_BASE_URL,
        "layer": parameter,
        "retrieved_at": now.isoformat(),
        "samples": [
            {"latitude": s.latitude, "longitude": s.longitude, "value": s.value, "unit": s.unit, "retrieved_at": s.retrieved_at.isoformat()}
            for s in samples
        ],
    }
    raw_path = RAW_DIR / "incois" / f"incois_{parameter}_samples_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    raw_size = _write_json(raw_path, raw_payload)
    raw_checksum = _sha256(raw_path.read_bytes())
    print(f"Raw samples saved: {raw_path.relative_to(REPO_ROOT)} ({raw_size:,} bytes)")

    print("Fetching one real WMS GetMap reference image...")
    png_bytes = incois_wms.fetch_reference_map_png(parameter=parameter, min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon)
    png_path = RAW_DIR / "incois" / f"incois_{parameter}_reference_map_{now.strftime('%Y%m%dT%H%M%SZ')}.png"
    png_size = _write_bytes(png_path, png_bytes)
    png_checksum = _sha256(png_bytes)
    print(f"Raw reference PNG saved: {png_path.relative_to(REPO_ROOT)} ({png_size:,} bytes)")

    features = [
        {"type": "Feature", "properties": {"value": s.value, "unit": s.unit, "parameter": parameter}, "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]}}
        for s in valid
    ]
    processed = {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "dataset": label,
            "parameter": parameter,
            "provider": incois_wms.INCOIS_PROVIDER,
            "source_url": incois_wms.INCOIS_SOURCE_URL,
            "access_method": f"OGC WMS GetFeatureInfo, layer {parameter!r}, {incois_wms.INCOIS_WMS_BASE_URL}",
            "acquired_at": now.isoformat(),
            "crs": "EPSG:4326",
            "unit": incois_wms.PARAMETER_UNITS[parameter],
            "unit_confidence": "inferred from value ranges and INCOIS's published PFZ methodology — not independently confirmed via service metadata (see app.data.incois_wms module docstring)",
            "bbox": {"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon},
            "grid_resolution": f"{INCOIS_SAMPLES_PER_AXIS}x{INCOIS_SAMPLES_PER_AXIS} bounded point samples",
            "sample_count_requested": len(samples),
            "sample_count_with_value": len(valid),
            "temporal_semantics": "single current operational snapshot — no WMS time dimension is advertised by this service",
            "authoritative": True,
            "classification": "dynamic",
        },
    }
    processed_path = PROCESSED_DIR / f"incois_{parameter}_orca_bbox.geojson"
    processed_size = _write_json(processed_path, processed)
    processed_checksum = _sha256(processed_path.read_bytes())
    print(f"Processed artifact saved: {processed_path.relative_to(REPO_ROOT)} ({processed_size:,} bytes)")

    return {
        "raw_path": str(raw_path.relative_to(REPO_ROOT)), "raw_size_bytes": raw_size, "raw_checksum_sha256": raw_checksum,
        "reference_png_path": str(png_path.relative_to(REPO_ROOT)), "reference_png_size_bytes": png_size, "reference_png_checksum_sha256": png_checksum,
        "processed_path": str(processed_path.relative_to(REPO_ROOT)), "processed_size_bytes": processed_size, "processed_checksum_sha256": processed_checksum,
        "sample_count_requested": len(samples), "sample_count_with_value": len(valid),
        "value_min": min((s.value for s in valid), default=None), "value_max": max((s.value for s in valid), default=None),
    }


def main() -> None:
    settings = get_settings()
    bbox = settings.demo_bbox
    now = datetime.now(timezone.utc)

    print("Phase 1 — Marine Data Foundation acquisition")
    print(f"ORCA demo bbox (UNCHANGED, from app.config.Settings.demo_bbox): {bbox.min_lat}, {bbox.min_lon} to {bbox.max_lat}, {bbox.max_lon}")

    manifest: dict = {"generated_at": now.isoformat(), "demo_bbox": {"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon}, "datasets": {}}

    try:
        gebco_result = acquire_gebco(bbox, now)
        manifest["datasets"]["gebco_bathymetry"] = {"status": "acquired", **gebco_result}
    except Exception as exc:  # noqa: BLE001 — report, never crash silently or fabricate
        print(f"GEBCO acquisition FAILED: {exc}")
        manifest["datasets"]["gebco_bathymetry"] = {"status": "failed", "error": str(exc)}

    for parameter, label in (("chl", "INCOIS Chlorophyll Concentration"), ("sst", "INCOIS Sea Surface Temperature")):
        try:
            result = acquire_incois(parameter, label, bbox, now)
            manifest["datasets"][f"incois_{parameter}"] = {"status": "acquired", **result}
        except Exception as exc:  # noqa: BLE001
            print(f"INCOIS {parameter} acquisition FAILED: {exc}")
            manifest["datasets"][f"incois_{parameter}"] = {"status": "failed", "error": str(exc)}

    manifest_path = PROCESSED_DIR / "phase1_data_manifest.json"
    manifest_size = _write_json(manifest_path, manifest)
    print(f"\nManifest saved: {manifest_path.relative_to(REPO_ROOT)} ({manifest_size:,} bytes)")

    # app.agents.gis.agent.GISGeofencingAgent.get_static_dataset_status
    # caches its result in Redis for gis_cache_ttl_seconds (24h default) —
    # correct for a status that rarely changes, but a fresh acquisition
    # MUST invalidate it immediately, or the API keeps serving the
    # pre-acquisition "not_acquired" answer for up to a day (found and
    # fixed live during this task). Best-effort: a Redis outage here must
    # never fail the acquisition itself, only its immediate visibility.
    try:
        from app.services.cache import get_client as get_redis_client

        redis_client = get_redis_client()
        for dataset_name in ("gebco_bathymetry", "incois_chl", "incois_sst"):
            redis_client.delete(f"orca:agent:gis:dataset_status:{dataset_name}")
        print("Invalidated cached dataset-status entries in Redis.")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not invalidate Redis cache (non-fatal): {exc}")

    print("\nRecording provenance in static_layer_sources (PostGIS)...")
    engine = get_engine()
    create_tables(engine)

    gebco_res = manifest["datasets"].get("gebco_bathymetry", {})
    if gebco_res.get("status") == "acquired":
        upsert_static_layer_source(
            engine,
            dataset_name="gebco_bathymetry",
            source_name="GEBCO Compilation Group (IHO/IOC UNESCO)",
            source_url=gebco.GEBCO_SOURCE_URL,
            data_tier="static",
            is_authoritative=True,
            acquisition_status="acquired",
            acquired_at=now,
            dataset_version=gebco.GEBCO_PRODUCT_NAME,
            geographic_coverage={"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon},
            processing_notes=(
                f"{gebco_res['sample_count_with_value']}/{gebco_res['sample_count_requested']} real point samples via WMS "
                f"GetFeatureInfo ({gebco.GEBCO_WMS_BASE_URL}, layer {gebco.GEBCO_ELEVATION_LAYER}); depth range "
                f"{gebco_res['depth_min_m']} to {gebco_res['depth_max_m']} m."
            ),
            metadata=gebco_res,
        )
        print("  gebco_bathymetry -> acquired")

    for parameter in ("chl", "sst"):
        res = manifest["datasets"].get(f"incois_{parameter}", {})
        if res.get("status") == "acquired":
            upsert_static_layer_source(
                engine,
                dataset_name=f"incois_{parameter}",
                source_name=incois_wms.INCOIS_PROVIDER,
                source_url=incois_wms.INCOIS_SOURCE_URL,
                data_tier="reference",
                is_authoritative=True,
                acquisition_status="acquired",
                acquired_at=now,
                dataset_version="INCOIS PFZ-TUNA-SST-CHL GeoServer (live operational layer, no version number published)",
                geographic_coverage={"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon},
                processing_notes=(
                    f"{res['sample_count_with_value']}/{res['sample_count_requested']} real point samples via WMS GetFeatureInfo "
                    f"({incois_wms.INCOIS_WMS_BASE_URL}, layer {parameter}); value range {res['value_min']} to {res['value_max']}."
                ),
                metadata=res,
            )
            print(f"  incois_{parameter} -> acquired")

    print("\nDone.")


if __name__ == "__main__":
    main()
