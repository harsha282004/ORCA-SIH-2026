"""Shared parsing for Open-Meteo's "hourly" response shape.

Both the Weather and Marine APIs return the same structural envelope
(``hourly_units`` + ``hourly.time[]`` + one array per parameter), so the
per-parameter validation/normalization loop is written once here and
called by both adapters. Everything else (base URL, required parameters,
source_type) stays adapter-specific in open_meteo_weather.py /
open_meteo_marine.py — this is not a generic multi-provider base, only a
shared step within the Open-Meteo family.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.data.base import RawResponse, SourceResponseError
from app.fabric.spatial import validate_point
from app.fabric.units import UnknownUnitError, normalize_unit
from app.models.contracts import Mode, NormalizedObservation, QualityMetadata, SourceType

HOURLY_STEP = timedelta(hours=1)


def _parse_times(times: list[str], source_name: str) -> list[datetime]:
    parsed: list[datetime] = []
    for t in times:
        try:
            parsed.append(datetime.fromisoformat(t).replace(tzinfo=timezone.utc))
        except (TypeError, ValueError) as exc:
            raise SourceResponseError(f"{source_name} returned an invalid timestamp: {t!r}") from exc
    return parsed


def _select_current_step(parsed_times: list[datetime], reference_time: datetime) -> int:
    """Pick the hourly step whose bucket [time, time+1h) contains `reference_time`
    — i.e. the forecast value that is actually current right now, not
    always the first element of the array (which is midnight UTC of the
    forecast's start day and may already be hours in the past by the time
    ORCA calls this). Falls back to the earliest step if `reference_time`
    is before the first available step (e.g. a request made fractionally
    before the API's own day boundary).
    """
    candidates = [i for i, t in enumerate(parsed_times) if t <= reference_time]
    if candidates:
        return max(candidates, key=lambda i: parsed_times[i])
    return 0


def parse_hourly_observations(
    raw: RawResponse,
    *,
    parameters: list[str],
    source_name: str,
    source_type: SourceType,
    mode: Mode,
) -> list[NormalizedObservation]:
    """Validate + normalize the hourly step that is current as of `raw.retrieved_at`.

    Phase 1 samples one representative time step per fetch (the current
    hour's forecast value) rather than ingesting the full multi-day
    series — sufficient to prove and test the full ingestion pipeline
    without building a time-series ingestion system prematurely. The
    step's validity window is treated as [observed_at, observed_at + 1h)
    to match Open-Meteo's hourly cadence — never a zero-width instant,
    which would make every observation EXPIRED the moment it is checked.
    """
    payload = raw.payload

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise SourceResponseError(f"{source_name} response missing 'hourly' block")

    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise SourceResponseError(f"{source_name} response missing 'hourly.time'")

    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if latitude is None or longitude is None:
        raise SourceResponseError(f"{source_name} response missing latitude/longitude")
    validate_point(latitude, longitude)

    parsed_times = _parse_times(times, source_name)
    time_index = _select_current_step(parsed_times, raw.retrieved_at)
    observed_at = parsed_times[time_index]

    units = payload.get("hourly_units", {})
    if not isinstance(units, dict):
        raise SourceResponseError(f"{source_name} response has a malformed 'hourly_units' block")

    observations: list[NormalizedObservation] = []

    for parameter in parameters:
        series = hourly.get(parameter)
        source_unit = units.get(parameter, "")

        value: float | None = None
        unit = source_unit or "unknown"
        quality = QualityMetadata()

        if not isinstance(series, list) or len(series) <= time_index:
            quality = QualityMetadata(is_missing=True, missing_reason=f"'{parameter}' missing from response")
        else:
            raw_value = series[time_index]
            if raw_value is None:
                quality = QualityMetadata(is_missing=True, missing_reason=f"'{parameter}' is null for this time step")
            else:
                try:
                    value, unit = normalize_unit(parameter, float(raw_value), source_unit)
                except (UnknownUnitError, TypeError, ValueError) as exc:
                    quality = QualityMetadata(is_missing=True, missing_reason=str(exc))

        observations.append(
            NormalizedObservation(
                source=source_name,
                source_type=source_type,
                source_tier="live",  # a successful real API response is genuinely live (§15) —
                parameter=parameter,  # independent of the session's ORCA_MODE (§16a)
                value=value,
                unit=unit,
                latitude=float(latitude),
                longitude=float(longitude),
                observed_at=observed_at,
                valid_from=observed_at,
                valid_to=observed_at + HOURLY_STEP,
                is_forecast=True,
                retrieved_at=raw.retrieved_at,
                mode=mode,
                is_live=True,
                quality=quality,
                metadata={"request_params": raw.request_params, "request_url": raw.request_url},
            )
        )

    return observations
