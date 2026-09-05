import pytest

from app.fabric.units import UnknownUnitError, canonical_unit_for, known_parameter, normalize_unit


def test_known_parameter() -> None:
    assert known_parameter("wave_height")
    assert not known_parameter("not_a_real_parameter")


def test_canonical_unit_for_known_parameter() -> None:
    assert canonical_unit_for("wind_speed_10m") == "m/s"
    assert canonical_unit_for("wave_height") == "m"
    assert canonical_unit_for("sea_surface_temperature") == "degC"


def test_canonical_unit_for_unknown_parameter_raises() -> None:
    with pytest.raises(UnknownUnitError):
        canonical_unit_for("not_a_real_parameter")


def test_wind_speed_kmh_to_ms() -> None:
    value, unit = normalize_unit("wind_speed_10m", 36.0, "km/h")
    assert unit == "m/s"
    assert value == pytest.approx(10.0)


def test_wind_speed_already_ms_is_identity() -> None:
    value, unit = normalize_unit("wind_speed_10m", 5.0, "m/s")
    assert value == pytest.approx(5.0)
    assert unit == "m/s"


def test_wind_speed_knots_to_ms() -> None:
    value, unit = normalize_unit("wind_speed_10m", 1.0, "kn")
    assert value == pytest.approx(0.514444)


def test_current_velocity_kmh_to_ms() -> None:
    value, unit = normalize_unit("ocean_current_velocity", 3.6, "km/h")
    assert value == pytest.approx(1.0)
    assert unit == "m/s"


def test_temperature_fahrenheit_to_celsius() -> None:
    value, unit = normalize_unit("temperature_2m", 32.0, "°F")
    assert value == pytest.approx(0.0)
    assert unit == "degC"


def test_direction_degree_symbol_is_identity() -> None:
    value, unit = normalize_unit("wind_direction_10m", 245.0, "°")
    assert value == 245.0
    assert unit == "degree"


def test_wave_height_meters_is_identity() -> None:
    value, unit = normalize_unit("wave_height", 1.4, "m")
    assert value == 1.4
    assert unit == "m"


def test_weathercode_is_dimensionless_identity() -> None:
    value, unit = normalize_unit("weathercode", 95.0, "wmo code")
    assert value == 95.0
    assert unit == "wmo_code"


def test_unknown_source_unit_is_rejected() -> None:
    with pytest.raises(UnknownUnitError):
        normalize_unit("wind_speed_10m", 10.0, "furlongs_per_fortnight")


def test_unknown_parameter_is_rejected() -> None:
    with pytest.raises(UnknownUnitError):
        normalize_unit("not_a_real_parameter", 10.0, "m/s")
