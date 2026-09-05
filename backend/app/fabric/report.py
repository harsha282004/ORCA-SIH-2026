"""Reproducible inspection of a batch of normalized observations — Phase 1's
data validation report requirement. Operates on in-memory
``NormalizedObservation`` lists, so it works whether or not PostGIS is
reachable (see scripts/ingest_demo_observations.py for the CLI wrapper).
"""
from __future__ import annotations

from app.models.contracts import NormalizedObservation


def summarize(observations: list[NormalizedObservation]) -> dict:
    if not observations:
        return {"count": 0}

    by_source: dict[str, int] = {}
    parameters_and_units: dict[str, str] = {}
    temporal_validity_counts: dict[str, int] = {}
    missing_count = 0
    invalid_count = 0
    lats: list[float] = []
    lons: list[float] = []
    observed_times = []
    retrieved_times = []
    modes: set[str] = set()

    for obs in observations:
        by_source[obs.source] = by_source.get(obs.source, 0) + 1
        parameters_and_units[obs.parameter] = obs.unit
        temporal_validity_counts[obs.temporal_validity] = temporal_validity_counts.get(obs.temporal_validity, 0) + 1
        if obs.quality.is_missing:
            missing_count += 1
        if obs.quality.validation_status == "invalid":
            invalid_count += 1
        lats.append(obs.latitude)
        lons.append(obs.longitude)
        if obs.observed_at is not None:
            observed_times.append(obs.observed_at)
        retrieved_times.append(obs.retrieved_at)
        modes.add(obs.mode)

    return {
        "count": len(observations),
        "by_source": by_source,
        "parameters_and_units": parameters_and_units,
        "missing_count": missing_count,
        "invalid_count": invalid_count,
        "temporal_validity_counts": temporal_validity_counts,
        "geographic_extent": {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lon": min(lons),
            "max_lon": max(lons),
        },
        "observed_time_range": {
            "min": min(observed_times).isoformat() if observed_times else None,
            "max": max(observed_times).isoformat() if observed_times else None,
        },
        "retrieved_time_range": {
            "min": min(retrieved_times).isoformat(),
            "max": max(retrieved_times).isoformat(),
        },
        "modes": sorted(modes),
    }
