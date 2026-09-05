import pytest
from pydantic import ValidationError

from app.risk.config import (
    ConfidenceWeights,
    CycloneProxyWeights,
    RiskThresholds,
    RiskWeights,
    SafetyConfig,
    WeightSumError,
    check_weights_sum_to_one,
    get_risk_config,
)


def test_default_risk_weights_match_architecture_exactly() -> None:
    cfg = get_risk_config()
    weights = cfg.risk_weights
    assert weights.wave == pytest.approx(0.25)
    assert weights.wind == pytest.approx(0.15)
    assert weights.advisory_or_hazard_flag == pytest.approx(0.20)
    assert weights.lightning_thunderstorm_proxy == pytest.approx(0.10)
    assert weights.restricted_zone_distance == pytest.approx(0.15)
    assert weights.coast_distance == pytest.approx(0.10)
    assert weights.data_confidence_penalty == pytest.approx(0.05)


def test_default_risk_thresholds_match_architecture_exactly() -> None:
    cfg = get_risk_config()
    assert cfg.risk_thresholds.low_max == pytest.approx(0.33)
    assert cfg.risk_thresholds.moderate_max == pytest.approx(0.66)


def test_default_confidence_weights_match_architecture_exactly() -> None:
    cfg = get_risk_config()
    assert cfg.confidence_weights.freshness == pytest.approx(0.40)
    assert cfg.confidence_weights.completeness == pytest.approx(0.35)
    assert cfg.confidence_weights.agreement == pytest.approx(0.25)


def test_check_weights_sum_to_one_raises_directly() -> None:
    # The underlying validator function, unit-tested directly rather than
    # through Pydantic's wrapping.
    with pytest.raises(WeightSumError):
        check_weights_sum_to_one("test_weights", {"a": 0.5, "b": 0.6})


def test_risk_weights_must_sum_to_one() -> None:
    # Pydantic wraps a model_validator's raised exception in ValidationError
    # — the WeightSumError is still the cause, but callers see ValidationError.
    with pytest.raises(ValidationError):
        RiskWeights(
            wave=0.5,
            wind=0.5,
            advisory_or_hazard_flag=0.5,
            lightning_thunderstorm_proxy=0.0,
            restricted_zone_distance=0.0,
            coast_distance=0.0,
            data_confidence_penalty=0.0,
        )


def test_risk_weights_not_silently_normalized() -> None:
    # A weight set that is close but not exactly 1.0 must still fail —
    # never silently rescaled for "convenience".
    with pytest.raises(ValidationError):
        RiskWeights(
            wave=0.25,
            wind=0.15,
            advisory_or_hazard_flag=0.20,
            lightning_thunderstorm_proxy=0.10,
            restricted_zone_distance=0.15,
            coast_distance=0.10,
            data_confidence_penalty=0.10,  # sums to 1.05, not 1.0
        )


def test_confidence_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        ConfidenceWeights(freshness=0.5, completeness=0.5, agreement=0.5)


def test_cyclone_proxy_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        CycloneProxyWeights(
            pressure_tendency=1.0, sustained_wind=1.0, wind_gust=0.0, spatial_persistence=0.0, temporal_persistence=0.0
        )


def test_risk_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        RiskThresholds(low_max=0.7, moderate_max=0.3)


def test_safety_config_bounds() -> None:
    with pytest.raises(ValueError):
        SafetyConfig(min_confidence_threshold=1.5)
    with pytest.raises(ValueError):
        SafetyConfig(min_confidence_threshold=-0.1)
