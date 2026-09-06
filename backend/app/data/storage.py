"""PostGIS-backed storage for Phase 1 data (architecture.md §33 pattern, §36).

Only two tables — exactly what the data foundation itself needs:

- ``environmental_observations`` — normalized Open-Meteo observations, one
  row per (source, parameter, time step, location).
- ``static_layer_sources`` — a provenance registry recording the
  acquisition status of each static GIS dataset the architecture names
  (Natural Earth, GEBCO, WDPA, Marine Regions), per architecture.md §17's
  provenance requirements. It does NOT hold geometry data itself yet —
  Phase 1 does not perform the bulk static-data acquisition (see
  docs/demo_region.md for why), so this table honestly records
  "not_acquired" rather than fabricating a loaded layer.

The final ORCA schema (queries, agent_runs, recommendations, risk_cells,
geofences, routes, ...) from architecture.md §33 is intentionally NOT
created here — those are later phases' business tables.

Parameterized via SQLAlchemy Core throughout (architecture.md §37) — no
string-concatenated SQL.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import Boolean, Column, DateTime, Float, Index, MetaData, String, Table, Text, func, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.models.contracts import NormalizedObservation

metadata_obj = MetaData()

environmental_observations = Table(
    "environmental_observations",
    metadata_obj,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("source", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("source_tier", String, nullable=False),
    Column("parameter", String, nullable=False),
    Column("value", Float, nullable=True),
    Column("unit", String, nullable=False),
    Column("geom", Geometry(geometry_type="POINT", srid=4326), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("is_forecast", Boolean, nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("mode", String, nullable=False),
    Column("is_live", Boolean, nullable=False),
    Column("is_missing", Boolean, nullable=False),
    Column("missing_reason", Text, nullable=True),
    Column("validation_status", String, nullable=False),
    Column("validation_errors", JSONB, nullable=False),
    Column("temporal_validity", String, nullable=False),
    Column("metadata", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

Index(
    "ix_environmental_observations_geom",
    environmental_observations.c.geom,
    postgresql_using="gist",
)
Index(
    "ix_environmental_observations_parameter_observed_at",
    environmental_observations.c.parameter,
    environmental_observations.c.observed_at,
)

static_layer_sources = Table(
    "static_layer_sources",
    metadata_obj,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("dataset_name", String, nullable=False, unique=True),
    Column("source_name", String, nullable=False),
    Column("source_url", String, nullable=True),
    Column("data_tier", String, nullable=False),  # static | reference | demo
    Column("is_authoritative", Boolean, nullable=False),
    Column("acquisition_status", String, nullable=False),  # not_acquired | acquired | processed | loaded
    Column("acquired_at", DateTime(timezone=True), nullable=True),
    Column("dataset_version", String, nullable=True),
    Column("geographic_coverage", JSONB, nullable=True),
    Column("crs", String, nullable=False, server_default="EPSG:4326"),
    Column("processing_notes", Text, nullable=True),
    # Phase 1 (Marine Data Foundation) addition — extensible provenance
    # detail that doesn't warrant its own narrow column per field (file
    # sizes, checksums, resolution, feature/cell counts, license). Mirrors
    # the same JSONB "escape hatch" pattern `environmental_observations
    # .metadata` already uses; no new column-per-fact sprawl.
    Column("metadata", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def create_tables(engine: Engine) -> None:
    metadata_obj.create_all(engine, checkfirst=True)
    _ensure_schema_upgrades(engine)


def _ensure_schema_upgrades(engine: Engine) -> None:
    """Lightweight, idempotent ALTERs for columns added to an ALREADY-
    created table after its first deployment — no Alembic/migration
    framework introduced (frozen architecture), just the same
    `IF NOT EXISTS` discipline Postgres itself provides. Safe to run on
    every startup/script invocation.
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE static_layer_sources ADD COLUMN IF NOT EXISTS metadata JSONB"))


def _observation_to_row(obs: NormalizedObservation) -> dict:
    return {
        "id": obs.observation_id,
        "source": obs.source,
        "source_type": obs.source_type,
        "source_tier": obs.source_tier,
        "parameter": obs.parameter,
        "value": obs.value,
        "unit": obs.unit,
        "geom": from_shape(Point(obs.longitude, obs.latitude), srid=4326),
        "observed_at": obs.observed_at,
        "valid_from": obs.valid_from,
        "valid_to": obs.valid_to,
        "is_forecast": obs.is_forecast,
        "retrieved_at": obs.retrieved_at,
        "mode": obs.mode,
        "is_live": obs.is_live,
        "is_missing": obs.quality.is_missing,
        "missing_reason": obs.quality.missing_reason,
        "validation_status": obs.quality.validation_status,
        "validation_errors": obs.quality.validation_errors,
        "temporal_validity": obs.temporal_validity,
        "metadata": obs.metadata,
    }


def insert_observations(engine: Engine, observations: list[NormalizedObservation]) -> int:
    if not observations:
        return 0
    rows = [_observation_to_row(o) for o in observations]
    with engine.begin() as conn:
        conn.execute(insert(environmental_observations), rows)
    return len(rows)


def upsert_static_layer_source(
    engine: Engine,
    *,
    dataset_name: str,
    source_name: str,
    data_tier: str,
    is_authoritative: bool,
    acquisition_status: str,
    source_url: str | None = None,
    acquired_at: datetime | None = None,
    dataset_version: str | None = None,
    geographic_coverage: dict | None = None,
    processing_notes: str | None = None,
    metadata: dict | None = None,
) -> None:
    stmt = pg_insert(static_layer_sources).values(
        id=str(uuid.uuid4()),
        dataset_name=dataset_name,
        source_name=source_name,
        source_url=source_url,
        data_tier=data_tier,
        is_authoritative=is_authoritative,
        acquisition_status=acquisition_status,
        acquired_at=acquired_at,
        dataset_version=dataset_version,
        geographic_coverage=geographic_coverage,
        processing_notes=processing_notes,
        metadata=metadata,
    )
    update_cols = {
        col.name: col
        for col in stmt.excluded
        if col.name not in ("id", "dataset_name", "created_at")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["dataset_name"], set_=update_cols)
    with engine.begin() as conn:
        conn.execute(stmt)


def list_static_layer_sources(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(select(static_layer_sources))
        return [dict(row._mapping) for row in result]
