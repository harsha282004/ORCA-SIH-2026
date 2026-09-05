"""Timestamp normalization and the Temporal Validity Gate — architecture.md §17.

Deterministic only — no LLM, no forecasting model. Three timestamps are
kept explicitly distinct, per architecture.md §14/§17:

    observed_at    — when the observation/forecast VALUE is valid for
    retrieved_at   — when ORCA fetched it (never confused with observed_at)
    requested_time — the time the caller actually cares about ("now", or a
                     future query's resolved time window)

``evaluate_temporal_validity`` is the gate itself: it decides whether a
piece of data may be treated as currently usable, and returns one of the
five statuses named in the Phase 1 spec.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.contracts import TemporalValidityStatus


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def freshness_seconds(retrieved_at: datetime, reference_time: datetime) -> float:
    """How long ago (in seconds) `retrieved_at` was, relative to `reference_time`."""
    return (to_utc(reference_time) - to_utc(retrieved_at)).total_seconds()


def evaluate_temporal_validity(
    *,
    observed_at: datetime | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
    retrieved_at: datetime,
    requested_time: datetime,
    max_staleness: timedelta,
) -> TemporalValidityStatus:
    """Architecture.md §17's Temporal Validity Gate, as a pure function.

    - MISSING_TIMESTAMP: the data has no resolvable temporal anchor at all.
    - INVALID_TIMESTAMP: timestamps are present but internally inconsistent
      (e.g. valid_from after valid_to), or lack timezone information.
    - EXPIRED: requested_time falls outside the [valid_from, valid_to] window.
    - STALE: the data is still within its validity window, but was
      retrieved too long ago relative to the requested time.
    - VALID: none of the above — the data may be treated as current.
    """
    if observed_at is None or valid_from is None or valid_to is None:
        return "MISSING_TIMESTAMP"

    for dt in (observed_at, valid_from, valid_to, retrieved_at, requested_time):
        if dt.tzinfo is None:
            return "INVALID_TIMESTAMP"

    if valid_from > valid_to:
        return "INVALID_TIMESTAMP"

    if requested_time < valid_from or requested_time > valid_to:
        return "EXPIRED"

    if freshness_seconds(retrieved_at, requested_time) > max_staleness.total_seconds():
        return "STALE"

    return "VALID"
