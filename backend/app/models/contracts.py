"""Phase 1 data contracts.

Two layers, matching two different parts of the frozen architecture:

1. ``NormalizedObservation`` — the Marine Data Fabric's internal normalized
   observation. It implements the "common schema (per observation)" from
   architecture.md §13, extended with the missingness/quality/temporal-
   validity/live-vs-demo bookkeeping that Phase 1 explicitly requires
   (architecture.md §14-17, §29 data-quality expectations). Source adapters
   produce these; the Fabric stores/serves them. Later-phase agents are
   meant to consume this shape, never a raw provider response.

2. ``Evidence`` — the verbatim Pydantic contract from architecture.md §12,
   used once real agents exist (Phase 4+) to pass data between agents.
   ``NormalizedObservation.to_evidence()`` converts one into the other.
   Phase 1 has no agents to hand these to yet; the conversion exists so a
   later phase does not need a new contract.

No confidence/risk scoring happens here — that is the Risk Engine's job
(architecture.md §22, Phase 2), not the data foundation's.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SourceTier = Literal["live", "cached", "static", "reference", "synthetic"]
SourceType = Literal[
    "official_advisory", "official_observation", "forecast", "satellite_derived", "orca_derived"
]
Mode = Literal["live", "demo"]

TemporalValidityStatus = Literal["VALID", "STALE", "EXPIRED", "INVALID_TIMESTAMP", "MISSING_TIMESTAMP"]


class QualityMetadata(BaseModel):
    """Describes data quality; does not claim scientific certainty (architecture.md §22)."""

    is_missing: bool = False
    missing_reason: str | None = None
    validation_status: Literal["valid", "invalid"] = "valid"
    validation_errors: list[str] = Field(default_factory=list)
    spatial_valid: bool = True


class Evidence(BaseModel):
    """Verbatim agent contract — architecture.md §12. Not used until agents exist (Phase 4+)."""

    evidence_id: str
    source: str
    source_type: SourceType
    source_tier: SourceTier
    parameter: str
    value: float
    unit: str
    timestamp: datetime
    valid_from: datetime
    valid_to: datetime
    spatial_extent: dict
    retrieval_time: datetime
    confidence: float


class AgentResult(BaseModel):
    """Verbatim contract from architecture.md §12 — first actually used in
    Phase 4's data agents (Weather/Oceanographic/GIS).

    Two fields beyond the literal §12 schema, both documented:

    - ``mode``: architecture.md §16a's session-type concept (live/demo),
      already established on ``NormalizedObservation`` in Phase 1. §12's
      AgentResult has no such field; Phase 4's task spec explicitly
      requires ORCA_MODE to be visible on every agent result, so it is
      added here rather than overloading ``source_tier`` (which already
      carries the live/cached/static/reference/synthetic provenance tier —
      a different, independent concern, per §16a).
    - ``temporal_validity_status``: the Temporal Validity Gate's verdict
      (VALID/STALE/EXPIRED/INVALID_TIMESTAMP/MISSING_TIMESTAMP, §17).
      §12's own ``temporal_validity`` field is a dict of
      ``{valid_from, valid_to, is_forecast}`` — the validity *window*, not
      the Gate's *verdict* on it. Phase 1 already built the verdict as a
      typed status string; it needed a home that doesn't collide with the
      literal schema's dict field.
    """

    status: Literal["ok", "degraded", "failed"]
    data: dict
    evidence: list[Evidence]
    confidence: float
    source_tier: SourceTier
    timestamp: datetime
    spatial_extent: dict
    temporal_validity: dict  # {valid_from, valid_to, is_forecast}
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    mode: Mode
    temporal_validity_status: TemporalValidityStatus


class ConflictObject(BaseModel):
    """Verbatim contract from architecture.md §12/§20. First actually used
    in Phase 5's orchestration graph. Evidence Arbitration and Conflict
    Resolution themselves (§19-20 — reconciling disagreeing sources) are
    NOT implemented this phase: only one source exists per domain
    (Open-Meteo), so there is nothing to arbitrate yet. This contract
    exists so the graph state has the correct structural interface ready
    — `conflicts` lists built this phase are honestly always empty, never
    a fabricated conflict to demonstrate the type exists.
    """

    conflict_id: str
    signals: list[Evidence]
    resolution: str
    precedence_rule: str
    user_visible: bool = True


class NormalizedObservation(BaseModel):
    """Marine Data Fabric's internal normalized observation (architecture.md §13)."""

    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    source: str
    source_type: SourceType
    source_tier: SourceTier

    parameter: str
    value: float | None
    unit: str

    latitude: float
    longitude: float
    crs: Literal["EPSG:4326"] = "EPSG:4326"

    observed_at: datetime | None  # when the value is valid FOR (§13 "timestamp")
    valid_from: datetime | None
    valid_to: datetime | None  # §13 "valid_until"
    is_forecast: bool

    retrieved_at: datetime  # when ORCA fetched it — never confused with observed_at

    mode: Mode  # the ORCA_MODE of the session that produced this (§16a)
    is_live: bool  # True iff source_tier == "live" — enforced below, never independently settable

    quality: QualityMetadata = Field(default_factory=QualityMetadata)
    temporal_validity: TemporalValidityStatus = "MISSING_TIMESTAMP"

    metadata: dict = Field(default_factory=dict)

    @field_validator("latitude")
    @classmethod
    def _lat_range(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError(f"latitude {v} out of range [-90, 90]")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon_range(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError(f"longitude {v} out of range [-180, 180]")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "NormalizedObservation":
        if self.value is None and not self.quality.is_missing:
            raise ValueError("value is None but quality.is_missing is False")
        if self.value is not None and self.quality.is_missing:
            raise ValueError("quality.is_missing is True but a value is present")
        if self.valid_from is not None and self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError(f"valid_from ({self.valid_from}) must be <= valid_to ({self.valid_to})")
        expected_is_live = self.source_tier == "live"
        if self.is_live != expected_is_live:
            # Structural enforcement of architecture.md §16a: demo/synthetic/static/
            # cached/reference data must never silently present itself as live.
            raise ValueError(
                f"is_live={self.is_live} is inconsistent with source_tier={self.source_tier!r}; "
                "is_live must equal (source_tier == 'live')"
            )
        return self

    def to_evidence(self, *, confidence: float) -> Evidence:
        if self.value is None:
            raise ValueError("cannot convert a missing observation to Evidence")
        if self.observed_at is None or self.valid_from is None or self.valid_to is None:
            raise ValueError("cannot convert an observation without resolved timestamps to Evidence")
        return Evidence(
            evidence_id=self.observation_id,
            source=self.source,
            source_type=self.source_type,
            source_tier=self.source_tier,
            parameter=self.parameter,
            value=self.value,
            unit=self.unit,
            timestamp=self.observed_at,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
            spatial_extent={"type": "Point", "coordinates": [self.longitude, self.latitude]},
            retrieval_time=self.retrieved_at,
            confidence=confidence,
        )
