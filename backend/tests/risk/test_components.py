import pytest

from app.risk.components import (
    COAST_DISTANCE_SATURATION_KM,
    RESTRICTED_ZONE_SATURATION_KM,
    WAVE_SATURATION_M,
    WIND_SATURATION_MS,
    advisory_or_hazard_risk,
    coast_distance_risk,
    data_confidence_penalty_risk,
    restricted_zone_distance_risk,
    wave_risk,
    wind_risk,
)


def test_wave_risk_zero_at_zero() -> None:
    assert wave_risk(0.0) == 0.0


def test_wave_risk_saturates_at_one() -> None:
    assert wave_risk(WAVE_SATURATION_M) == 1.0
    assert wave_risk(WAVE_SATURATION_M * 2) == 1.0


def test_wave_risk_rejects_negative() -> None:
    with pytest.raises(ValueError):
        wave_risk(-1.0)


def test_wave_risk_rejects_none() -> None:
    with pytest.raises(ValueError):
        wave_risk(None)


def test_wind_risk_zero_at_zero() -> None:
    assert wind_risk(0.0) == 0.0


def test_wind_risk_saturates_at_one() -> None:
    assert wind_risk(WIND_SATURATION_MS) == 1.0
    assert wind_risk(WIND_SATURATION_MS * 10) == 1.0


def test_wind_risk_rejects_negative() -> None:
    with pytest.raises(ValueError):
        wind_risk(-5.0)


def test_advisory_or_hazard_risk_none_active() -> None:
    assert advisory_or_hazard_risk("none") == 0.0


def test_advisory_or_hazard_risk_high() -> None:
    assert advisory_or_hazard_risk("high") == 1.0


def test_advisory_or_hazard_risk_unknown_level_rejected() -> None:
    with pytest.raises(ValueError):
        advisory_or_hazard_risk("catastrophic")


def test_advisory_or_hazard_risk_cyclone_proxy_dominates_when_higher() -> None:
    assert advisory_or_hazard_risk("none", cyclone_proxy_score=0.9) == 0.9


def test_advisory_or_hazard_risk_advisory_dominates_when_higher() -> None:
    assert advisory_or_hazard_risk("high", cyclone_proxy_score=0.1) == 1.0


def test_advisory_or_hazard_risk_rejects_out_of_range_cyclone_score() -> None:
    with pytest.raises(ValueError):
        advisory_or_hazard_risk("none", cyclone_proxy_score=1.5)


def test_restricted_zone_distance_risk_at_boundary_is_max() -> None:
    assert restricted_zone_distance_risk(0.0) == 1.0


def test_restricted_zone_distance_risk_decays_to_zero() -> None:
    assert restricted_zone_distance_risk(RESTRICTED_ZONE_SATURATION_KM) == 0.0
    assert restricted_zone_distance_risk(RESTRICTED_ZONE_SATURATION_KM * 5) == 0.0


def test_restricted_zone_distance_risk_matches_architecture_example() -> None:
    # architecture.md §22 worked example uses 6.2km with a 10km saturation
    # assumption documented in components.py — not claimed to reproduce
    # the architecture's own 0.30 exactly (that curve isn't specified),
    # but must be monotonically between the boundary and saturation values.
    value = restricted_zone_distance_risk(6.2)
    assert 0.0 < value < 1.0


def test_restricted_zone_distance_risk_rejects_negative() -> None:
    with pytest.raises(ValueError):
        restricted_zone_distance_risk(-1.0)


def test_coast_distance_risk_zero_at_coast() -> None:
    assert coast_distance_risk(0.0) == 0.0


def test_coast_distance_risk_saturates() -> None:
    assert coast_distance_risk(COAST_DISTANCE_SATURATION_KM) == 1.0
    assert coast_distance_risk(COAST_DISTANCE_SATURATION_KM * 2) == 1.0


def test_coast_distance_risk_rejects_negative() -> None:
    with pytest.raises(ValueError):
        coast_distance_risk(-1.0)


def test_data_confidence_penalty_full_confidence_no_penalty() -> None:
    assert data_confidence_penalty_risk(1.0) == 0.0


def test_data_confidence_penalty_zero_confidence_max_penalty() -> None:
    assert data_confidence_penalty_risk(0.0) == 1.0


def test_data_confidence_penalty_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        data_confidence_penalty_risk(1.5)
    with pytest.raises(ValueError):
        data_confidence_penalty_risk(-0.1)
