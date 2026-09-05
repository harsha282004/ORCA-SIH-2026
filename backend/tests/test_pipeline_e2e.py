"""End-to-end Phase 1 pipeline test:

    SOURCE -> RAW -> VALIDATION -> NORMALIZATION -> FABRIC -> TEMPORAL VALIDITY -> POSTGIS

Split into two markers because they depend on different infrastructure:
  - `live`: real Open-Meteo call through the Fabric's temporal validity gate
    (network required, no database required).
  - `integration`: the same, plus the final PostGIS write (network AND a
    live PostgreSQL/PostGIS instance required).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.data.open_meteo_weather import OpenMeteoWeatherAdapter
from app.fabric.fabric import ingest
from app.fabric.report import summarize


@pytest.mark.live
def test_pipeline_through_temporal_validity() -> None:
    settings = get_settings()
    latitude, longitude = settings.demo_bbox.center()

    adapter = OpenMeteoWeatherAdapter(
        base_url=settings.open_meteo_weather_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    raw = adapter.fetch(latitude=latitude, longitude=longitude)
    observations = adapter.parse(raw, mode=settings.orca_mode)

    batch = ingest(
        observations,
        requested_time=datetime.now(timezone.utc),
        max_staleness=timedelta(minutes=settings.weather_max_staleness_minutes),
    )

    assert len(batch.observations) == len(observations)
    # freshly retrieved data, requested "now" -> must be VALID, not fabricated as such
    assert any(o.temporal_validity == "VALID" for o in batch.observations)

    report = summarize(batch.observations)
    assert report["count"] == len(observations)
    assert "open-meteo-weather" in report["by_source"]


@pytest.mark.integration
def test_pipeline_through_postgis_write() -> None:
    from app.data.storage import create_tables, insert_observations
    from app.services.database import get_engine

    settings = get_settings()
    latitude, longitude = settings.demo_bbox.center()

    adapter = OpenMeteoWeatherAdapter(
        base_url=settings.open_meteo_weather_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    raw = adapter.fetch(latitude=latitude, longitude=longitude)
    observations = adapter.parse(raw, mode=settings.orca_mode)

    batch = ingest(
        observations,
        requested_time=datetime.now(timezone.utc),
        max_staleness=timedelta(minutes=settings.weather_max_staleness_minutes),
    )

    engine = get_engine()
    create_tables(engine)
    inserted = insert_observations(engine, batch.observations)

    assert inserted == len(observations)
