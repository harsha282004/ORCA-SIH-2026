import pytest

from app.reasoning.confidence import ConfidenceInputs, compute_confidence
from app.risk.config import ConfidenceWeights, get_risk_config

ARCHITECTURE_WEIGHTS = get_risk_config().confidence_weights


def test_all_zero() -> None:
    inputs = ConfidenceInputs(freshness=0.0, completeness=0.0, agreement=0.0)
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == 0.0


def test_all_one() -> None:
    inputs = ConfidenceInputs(freshness=1.0, completeness=1.0, agreement=1.0)
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == pytest.approx(1.0)


def test_mixed_values_exact_weighted_output() -> None:
    inputs = ConfidenceInputs(freshness=1.0, completeness=0.0, agreement=0.0)
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == pytest.approx(0.40)

    inputs = ConfidenceInputs(freshness=0.0, completeness=1.0, agreement=0.0)
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == pytest.approx(0.35)

    inputs = ConfidenceInputs(freshness=0.0, completeness=0.0, agreement=1.0)
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == pytest.approx(0.25)


def test_architecture_style_example() -> None:
    # freshness 0.9, completeness 0.83 (5 of 6 factors present), agreement 1.0
    inputs = ConfidenceInputs(freshness=0.9, completeness=0.83, agreement=1.0)
    expected = 0.40 * 0.9 + 0.35 * 0.83 + 0.25 * 1.0
    assert compute_confidence(inputs, ARCHITECTURE_WEIGHTS) == pytest.approx(expected)


def test_bounds_enforced_on_inputs() -> None:
    with pytest.raises(Exception):
        ConfidenceInputs(freshness=1.5, completeness=0.5, agreement=0.5)
    with pytest.raises(Exception):
        ConfidenceInputs(freshness=-0.1, completeness=0.5, agreement=0.5)


def test_missing_input_is_not_silently_defaulted() -> None:
    with pytest.raises(Exception):
        ConfidenceInputs(freshness=0.5, agreement=0.5)  # completeness omitted, no default


def test_result_always_bounded() -> None:
    inputs = ConfidenceInputs(freshness=1.0, completeness=1.0, agreement=1.0)
    result = compute_confidence(inputs, ARCHITECTURE_WEIGHTS)
    assert 0.0 <= result <= 1.0


def test_determinism() -> None:
    inputs = ConfidenceInputs(freshness=0.7, completeness=0.6, agreement=0.9)
    results = {compute_confidence(inputs, ARCHITECTURE_WEIGHTS) for _ in range(10)}
    assert len(results) == 1


def test_confidence_weights_match_architecture() -> None:
    assert ARCHITECTURE_WEIGHTS.freshness == pytest.approx(0.40)
    assert ARCHITECTURE_WEIGHTS.completeness == pytest.approx(0.35)
    assert ARCHITECTURE_WEIGHTS.agreement == pytest.approx(0.25)
