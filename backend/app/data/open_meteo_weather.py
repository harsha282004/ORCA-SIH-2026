"""Open-Meteo Weather API adapter — architecture.md §14, primary live source.

No API key required. Requests only the parameters ORCA's later Risk Engine
(§22) will actually need: temperature, wind speed/direction, the WMO
weather code (§29b's thunderstorm/lightning proxy), and precipitation.
"""
from __future__ import annotations

from app.data.base import RawResponse, SourceAdapter
from app.data.open_meteo_common import parse_hourly_observations
from app.fabric.spatial import validate_point
from app.models.contracts import Mode, NormalizedObservation

REQUIRED_HOURLY_PARAMETERS = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "weathercode",
    "precipitation",
]


class OpenMeteoWeatherAdapter(SourceAdapter):
    source_name = "open-meteo-weather"

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
