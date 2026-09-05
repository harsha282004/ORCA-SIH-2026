"""Oceanographic static/demo fallback — architecture.md §16's third tier.
Same rationale as `app.agents.weather.static_fallback`: an explicit,
labeled SYNTHETIC placeholder (calm sea state), DEMO mode only.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models.contracts import NormalizedObservation, QualityMetadata

STATIC_SOURCE_NAME = "orca-static-marine-fallback"

_SYNTHETIC_VALUES: dict[str, tuple[float, str]] = {
    "wave_height": (0.5, "m"),
    "wave_direction": (250.0, "degree"),
    "wave_period": (6.0, "s"),
    "sea_surface_temperature": (28.0, "degC"),
    "ocean_current_velocity": (0.2, "m/s"),
    "ocean_current_direction": (200.0, "degree"),
}


def static_marine_observations(*, latitude: float, longitude: float, requested_time: datetime) -> list[NormalizedObservation]:
    valid_to = requested_time + timedelta(hours=1)
    observations = []
    for parameter, (value, unit) in _SYNTHETIC_VALUES.items():
        observations.append(
            NormalizedObservation(
                source=STATIC_SOURCE_NAME,
                source_type="orca_derived",
                source_tier="synthetic",
                parameter=parameter,
                value=value,
                unit=unit,
                latitude=latitude,
                longitude=longitude,
                observed_at=requested_time,
                valid_from=requested_time,
                valid_to=valid_to,
                is_forecast=False,
                retrieved_at=requested_time,
                mode="demo",
                is_live=False,
                quality=QualityMetadata(),
                metadata={"disclaimer": "DEMO DATA / SIMULATION — NOT LIVE DATA"},
            )
        )
    return observations
