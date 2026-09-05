"""Central unit normalization — architecture.md §13.

Every raw value coming from a source adapter passes through here before it
is allowed into a ``NormalizedObservation``. Conversion is looked up by
``(parameter, source_unit)`` rather than assumed, per architecture.md's
instruction to determine source units from the actual API response
(``hourly_units`` in Open-Meteo's case) rather than assuming they never
change. An unrecognized parameter or source unit is rejected — it is never
silently passed through or coerced.

Canonical units (chosen because they are what architecture.md §22's Risk
Engine formula consumes for wave/wind, and SI otherwise — nothing beyond
what the architecture already implies):

    wind_speed_10m            -> m/s
    wind_direction_10m         -> degree
    wave_height                  -> m
    wave_direction                 -> degree
    wave_period                      -> s
    sea_surface_temperature            -> degC
    ocean_current_velocity                -> m/s
    ocean_current_direction                  -> degree
    temperature_2m                              -> degC
    precipitation                                  -> mm
    weathercode                                      -> wmo_code (dimensionless, never converted)
"""
from __future__ import annotations


class UnknownUnitError(ValueError):
    """Raised when a (parameter, source_unit) combination is not known."""


CANONICAL_UNITS: dict[str, str] = {
    "wind_speed_10m": "m/s",
    "wind_direction_10m": "degree",
    "wave_height": "m",
    "wave_direction": "degree",
    "wave_period": "s",
    "sea_surface_temperature": "degC",
    "ocean_current_velocity": "m/s",
    "ocean_current_direction": "degree",
    "temperature_2m": "degC",
    "precipitation": "mm",
    "weathercode": "wmo_code",
}

_DIRECTION_PARAMETERS = {"wind_direction_10m", "wave_direction", "ocean_current_direction"}
_SPEED_PARAMETERS = {"wind_speed_10m", "ocean_current_velocity"}
_TEMPERATURE_PARAMETERS = {"temperature_2m", "sea_surface_temperature"}

_KMH_TO_MS = 1.0 / 3.6
_KN_TO_MS = 0.514444
_MPH_TO_MS = 0.44704


def _normalize_unit_key(unit: str) -> str:
    """Collapse a source unit string to alphanumeric-lowercase so we don't
    trip over encoding differences in the degree sign (°) across
    environments/locales — e.g. "km/h", "Â°", "wmo code" all become stable
    lookup keys.
    """
    return "".join(ch for ch in unit.lower() if ch.isalnum())


def known_parameter(parameter: str) -> bool:
    return parameter in CANONICAL_UNITS


def canonical_unit_for(parameter: str) -> str:
    try:
        return CANONICAL_UNITS[parameter]
    except KeyError as exc:
        raise UnknownUnitError(f"unknown parameter: {parameter!r}") from exc


def normalize_unit(parameter: str, value: float, source_unit: str) -> tuple[float, str]:
    """Convert (value, source_unit) for a known parameter into (value, canonical_unit)."""
    if not known_parameter(parameter):
        raise UnknownUnitError(f"unknown parameter: {parameter!r}")

    canonical_unit = CANONICAL_UNITS[parameter]
    key = _normalize_unit_key(source_unit)

    if parameter in _SPEED_PARAMETERS:
        if key == "ms":
            return value, canonical_unit
        if key == "kmh":
            return value * _KMH_TO_MS, canonical_unit
        if key == "kn":
            return value * _KN_TO_MS, canonical_unit
        if key == "mph":
            return value * _MPH_TO_MS, canonical_unit
        raise UnknownUnitError(f"unknown source unit {source_unit!r} for parameter {parameter!r}")

    if parameter in _TEMPERATURE_PARAMETERS:
        if key == "c":
            return value, canonical_unit
        if key == "f":
            return (value - 32.0) * 5.0 / 9.0, canonical_unit
        raise UnknownUnitError(f"unknown source unit {source_unit!r} for parameter {parameter!r}")

    if parameter in _DIRECTION_PARAMETERS:
        if key in ("", "deg", "degree", "degrees"):
            return value, canonical_unit
        raise UnknownUnitError(f"unknown source unit {source_unit!r} for parameter {parameter!r}")

    if parameter == "wave_height" and key == "m":
        return value, canonical_unit
    if parameter == "wave_period" and key == "s":
        return value, canonical_unit
    if parameter == "precipitation" and key == "mm":
        return value, canonical_unit
    if parameter == "weathercode" and key == "wmocode":
        return value, canonical_unit

    raise UnknownUnitError(f"unknown source unit {source_unit!r} for parameter {parameter!r}")
