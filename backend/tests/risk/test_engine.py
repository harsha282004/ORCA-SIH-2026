import pytest

from app.risk.config import RiskThresholds, RiskWeights, get_risk_config
from app.risk.engine import MissingRiskComponentError, NormalizedRiskComponents, classify_risk_level, compute_risk

ARCHITECTURE_WEIGHTS = get_risk_config().risk_weights
ARCHITECTURE_THRESHOLDS = get_risk_config().risk_thresholds


def all_components(value: float) -> NormalizedRiskComponents:
    return NormalizedRiskComponents(
        wave=value,
        wind=value,
        advisory_or_hazard_flag=value,
        lightning_thunderstorm_proxy=value,
        restricted_zone_distance=value,
        coast_distance=value,
        data_confidence_penalty=value,
    )


def test_all_components_zero() -> None:
    result = compute_risk(all_components(0.0), ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    assert result.score == 0.0
    assert result.level == "LOW"


def test_all_components_maximum() -> None:
    result = compute_risk(all_components(1.0), ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    assert result.score == pytest.approx(1.0)
    assert result.level == "HIGH"


def test_architecture_worked_example_exact() -> None:
    """architecture.md §22's own worked example:
    wave=0.55, wind=0.40, advisory=0.0, lightning=0.0,
    restricted_zone_distance=0.30, coast_distance=0.10, data_confidence_penalty=0.0
    -> 0.1375 + 0.060 + 0.0 + 0.0 + 0.045 + 0.010 + 0.0 = 0.2525 -> LOW
    """
    components = NormalizedRiskComponents(
        wave=0.55,
        wind=0.40,
        advisory_or_hazard_flag=0.0,
        lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.30,
        coast_distance=0.10,
        data_confidence_penalty=0.0,
    )
    result = compute_risk(components, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)

    assert result.score == pytest.approx(0.2525, abs=1e-9)
    assert result.level == "LOW"

    contributions = {f.name: f.contribution for f in result.factors}
    assert contributions["wave"] == pytest.approx(0.1375)
    assert contributions["wind"] == pytest.approx(0.060)
    assert contributions["restricted_zone_distance"] == pytest.approx(0.045)
    assert contributions["coast_distance"] == pytest.approx(0.010)


def test_weighted_combination_arbitrary_values() -> None:
    components = NormalizedRiskComponents(
        wave=1.0,
        wind=0.0,
        advisory_or_hazard_flag=0.0,
        lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0,
        coast_distance=0.0,
        data_confidence_penalty=0.0,
    )
    result = compute_risk(components, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    assert result.score == pytest.approx(0.25)  # exactly the wave weight


def test_weights_sum_validation_is_enforced_by_config_layer() -> None:
    with pytest.raises(Exception):
        RiskWeights(
            wave=1.0,
            wind=1.0,
            advisory_or_hazard_flag=0.0,
            lightning_thunderstorm_proxy=0.0,
            restricted_zone_distance=0.0,
            coast_distance=0.0,
            data_confidence_penalty=0.0,
        )


@pytest.mark.parametrize(
    "score,expected_level",
    [
        (0.0, "LOW"),
        (0.329999, "LOW"),
        (0.33, "MODERATE"),
        (0.659999, "MODERATE"),
        (0.66, "HIGH"),
        (1.0, "HIGH"),
    ],
)
def test_risk_level_boundary_values(score: float, expected_level: str) -> None:
    thresholds = RiskThresholds(low_max=0.33, moderate_max=0.66)
    assert classify_risk_level(score, thresholds) == expected_level


def test_invalid_component_value_above_one_rejected() -> None:
    with pytest.raises(Exception):
        NormalizedRiskComponents(
            wave=1.5,
            wind=0.0,
            advisory_or_hazard_flag=0.0,
            lightning_thunderstorm_proxy=0.0,
            restricted_zone_distance=0.0,
            coast_distance=0.0,
            data_confidence_penalty=0.0,
        )


def test_negative_component_value_rejected() -> None:
    with pytest.raises(Exception):
        NormalizedRiskComponents(
            wave=-0.1,
            wind=0.0,
            advisory_or_hazard_flag=0.0,
            lightning_thunderstorm_proxy=0.0,
            restricted_zone_distance=0.0,
            coast_distance=0.0,
            data_confidence_penalty=0.0,
        )


def test_missing_component_raises_rather_than_becoming_zero() -> None:
    components = NormalizedRiskComponents(
        wave=0.5,
        wind=None,
        advisory_or_hazard_flag=0.0,
        lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0,
        coast_distance=0.0,
        data_confidence_penalty=0.0,
    )
    with pytest.raises(MissingRiskComponentError) as exc_info:
        compute_risk(components, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    assert "wind" in str(exc_info.value)


def test_all_components_missing_lists_all_in_error() -> None:
    components = NormalizedRiskComponents()
    with pytest.raises(MissingRiskComponentError) as exc_info:
        compute_risk(components, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    message = str(exc_info.value)
    for name in (
        "wave",
        "wind",
        "advisory_or_hazard_flag",
        "lightning_thunderstorm_proxy",
        "restricted_zone_distance",
        "coast_distance",
        "data_confidence_penalty",
    ):
        assert name in message


def test_data_confidence_penalty_component_contributes() -> None:
    low_confidence = NormalizedRiskComponents(
        wave=0.0,
        wind=0.0,
        advisory_or_hazard_flag=0.0,
        lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0,
        coast_distance=0.0,
        data_confidence_penalty=1.0,
    )
    result = compute_risk(low_confidence, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS)
    assert result.score == pytest.approx(0.05)  # exactly the data_confidence_penalty weight


def test_determinism_same_inputs_same_output() -> None:
    components = all_components(0.42)
    results = {compute_risk(components, ARCHITECTURE_WEIGHTS, ARCHITECTURE_THRESHOLDS).score for _ in range(10)}
    assert len(results) == 1
