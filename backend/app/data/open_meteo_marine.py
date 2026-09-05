"""Open-Meteo Marine API adapter — architecture.md §14, primary live source.

No API key required. Requests wave height/direction/period, sea surface
temperature, and ocean current velocity/direction — the ocean-side inputs
architecture.md §22's Risk Engine and §21's Fishing Suitability Engine
will consume in later phases.
"""
from __future__ import annotations

from app.data.base import RawResponse, SourceAdapter
from app.data.open_meteo_common import parse_hourly_observations
from app.fabric.spatial import validate_point
from app.models.contracts import Mode, NormalizedObservation

REQUIRED_HOURLY_PARAMETERS = [
    "wave_height",
    "wave_direction",
    "wave_period",
    "sea_surface_temperature",
    "ocean_current_velocity",
    "ocean_current_direction",
]


class OpenMeteoMarineAdapter(SourceAdapter):
    source_name = "open-meteo-marine"

    def fetch(self, *, latitude: float, longitude: float) -> RawResponse:
        validate_point(latitude, longitude)
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(REQUIRED_HOURLY_PARAMETERS),
            "timezone": "UTC",
            "forecast_days": 1,
        }
        return self._get(params)

    def parse(self, raw: RawResponse, *, mode: Mode) -> list[NormalizedObservation]:
        return parse_hourly_observations(
            raw,
            parameters=REQUIRED_HOURLY_PARAMETERS,
            source_name=self.source_name,
            source_type="forecast",
            mode=mode,
        )
