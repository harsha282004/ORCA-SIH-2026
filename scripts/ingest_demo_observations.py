#!/usr/bin/env python
"""Phase 1 CLI: fetch live Open-Meteo data for the demo bbox, run it through
the full pipeline (fetch -> validate -> normalize -> fabric -> temporal
validity), and print a reproducible validation report. Optionally writes
the result to PostGIS and/or seeds the static-layer provenance registry.

Usage (from the repository root):
    python scripts/ingest_demo_observations.py
    python scripts/ingest_demo_observations.py --write-db
    python scripts/ingest_demo_observations.py --register-static-sources
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.data.base import SourceAdapterError  # noqa: E402
from app.data.open_meteo_marine import OpenMeteoMarineAdapter  # noqa: E402
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter  # noqa: E402
from app.fabric.fabric import ingest  # noqa: E402
from app.fabric.report import summarize  # noqa: E402
from app.models.contracts import NormalizedObservation  # noqa: E402
from app.models.geo import BBox  # noqa: E402


def _register_static_sources(engine, bbox: BBox) -> None:
    from app.data.storage import upsert_static_layer_source

    coverage = {"min_lat": bbox.min_lat, "min_lon": bbox.min_lon, "max_lat": bbox.max_lat, "max_lon": bbox.max_lon}
    bbox_note = "Deferred pending DEMO_BBOX confirmation (architecture.md §44) — see docs/demo_region.md."

    upsert_static_layer_source(
        engine,
        dataset_name="natural_earth_coastline",
        source_name="Natural Earth",
        source_url="https://www.naturalearthdata.com/",
        data_tier="static",
        is_authoritative=True,
        acquisition_status="not_acquired",
        geographic_coverage=coverage,
        processing_notes=bbox_note,
    )
    upsert_static_layer_source(
        engine,
        dataset_name="gebco_bathymetry",
        source_name="GEBCO Grid",
        source_url="https://www.gebco.net/",
        data_tier="static",
        is_authoritative=True,
        acquisition_status="not_acquired",
        geographic_coverage=coverage,
        processing_notes=bbox_note + " Fetch via WMS/OPeNDAP per architecture.md §14 (download app outage noted there).",
    )
    upsert_static_layer_source(
        engine,
        dataset_name="wdpa_protected_areas",
        source_name="WDPA / Protected Planet",
        source_url="https://www.protectedplanet.net/",
        data_tier="static",
        is_authoritative=True,
        acquisition_status="not_acquired",
        geographic_coverage=coverage,
        processing_notes=bbox_note + " Also requires a WDPA API token (architecture.md §14: free via request form, not yet obtained).",
    )
    upsert_static_layer_source(
        engine,
        dataset_name="marine_regions_eez",
        source_name="Marine Regions (VLIZ)",
        source_url="https://www.marineregions.org/",
        data_tier="static",
        is_authoritative=True,
        acquisition_status="not_acquired",
        geographic_coverage=coverage,
        processing_notes=bbox_note,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-db", action="store_true", help="Also write observations to PostGIS (requires a reachable database)")
    parser.add_argument(
        "--register-static-sources",
        action="store_true",
        help="Seed the static_layer_sources provenance registry as not_acquired (requires a reachable database)",
    )
    args = parser.parse_args()

    settings = get_settings()
    bbox = settings.demo_bbox
    latitude, longitude = bbox.center()

    print(f"ORCA_MODE = {settings.orca_mode}")
    print(f"DEMO_BBOX = min_lat={bbox.min_lat}, min_lon={bbox.min_lon}, max_lat={bbox.max_lat}, max_lon={bbox.max_lon}")
    print(f"Sampling point (bbox center): latitude={latitude}, longitude={longitude}")
    print()

    raw_data_dir = Path(settings.data_raw_dir)
    all_observations: list[NormalizedObservation] = []
    requested_time = datetime.now(timezone.utc)

    adapters = [
        (
            OpenMeteoWeatherAdapter(
                base_url=settings.open_meteo_weather_base_url,
                timeout_seconds=settings.http_timeout_seconds,
                raw_data_dir=raw_data_dir,
            ),
            settings.weather_max_staleness_minutes,
        ),
        (
            OpenMeteoMarineAdapter(
                base_url=settings.open_meteo_marine_base_url,
                timeout_seconds=settings.http_timeout_seconds,
                raw_data_dir=raw_data_dir,
            ),
            settings.marine_max_staleness_minutes,
        ),
    ]

    for adapter, max_staleness_minutes in adapters:
        print(f"--- {adapter.source_name} ---")
        try:
            raw = adapter.fetch(latitude=latitude, longitude=longitude)
        except SourceAdapterError as exc:
            print(f"  FETCH FAILED: {exc}")
            print()
            continue

        try:
            observations = adapter.parse(raw, mode=settings.orca_mode)
        except SourceAdapterError as exc:
            print(f"  PARSE FAILED: {exc}")
            print()
            continue

        batch = ingest(
            observations,
            requested_time=requested_time,
            max_staleness=timedelta(minutes=max_staleness_minutes),
        )
        all_observations.extend(batch.observations)

        for obs in batch.observations:
            value_str = "MISSING" if obs.quality.is_missing else f"{obs.value} {obs.unit}"
            print(f"  {obs.parameter:28s} {value_str:20s} temporal_validity={obs.temporal_validity}")
        print()

    print("=== Validation report ===")
    print(json.dumps(summarize(all_observations), indent=2, default=str))

    if args.write_db or args.register_static_sources:
        from app.data.storage import create_tables, insert_observations
        from app.services.database import get_engine

        engine = get_engine()
        create_tables(engine)

        if args.write_db:
            inserted = insert_observations(engine, all_observations)
            print(f"\nInserted {inserted} observations into PostGIS (environmental_observations).")

        if args.register_static_sources:
            _register_static_sources(engine, bbox)
            print("Registered static_layer_sources provenance rows (acquisition_status=not_acquired).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
