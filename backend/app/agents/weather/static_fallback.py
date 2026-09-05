"""Weather static/demo fallback — architecture.md §16's third tier.

Phase 1 never acquired a real climatology/demo weather dataset (no such
dataset exists in this repository). This is an explicit, clearly-labeled
SYNTHETIC placeholder (benign, calm conditions) — never a claim about real
weather. It exists solely so the 3-tier fallback table's "Static Fallback?
Yes" column (architecture.md §16, wind/weather row) has something honest
to point to, and — critically — architecture.md §16a restricts its use to
DEMO mode only: LIVE mode must never fall through to this.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models.contracts import Mode, NormalizedObservation, QualityMetadata

STATIC_SOURCE_NAME = "orca-static-weather-fallback"

_SYNTHETIC_VALUES: dict[str, tuple[float, str]] = {
    "temperature_2m": (27.0, "degC"),
    "wind_speed_10m": (4.0, "m/s"),
    "wind_direction_10m": (270.0, "degree"),
    "weathercode": (1.0, "wmo_code"),  # 1 = "mainly clear" — a deliberately benign placeholder
    "precipitation": (0.0, "mm"),
}


def static_weather_observations(*, latitude: float, longitude: float, requested_time: datetime) -> list[NormalizedObservation]:
    """A fixed, synthetic, demo-only weather snapshot. `source_tier="synthetic"`
    on every observation makes it structurally impossible for this to be
    mistaken for live/cached data downstream (see
    `NormalizedObservation`'s own `is_live == (source_tier == "live")`
    validator, Phase 1).
    """
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
