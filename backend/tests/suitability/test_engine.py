import pytest

from app.suitability.config import get_suitability_weights
from app.suitability.engine import evaluate_suitability
from app.suitability.models import PFZReference

WEIGHTS = get_suitability_weights()


def test_suitability_label_and_disclaimer_present() -> None:
    result = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS
    )
    assert result.label == "ORCA Fishing Suitability"
    assert "not the official PFZ" in result.disclaimer


def test_pfz_defaults_to_unavailable_when_not_supplied() -> None:
    result = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS
    )
    assert result.pfz_reference.status == "unavailable"
    assert result.pfz_reference.value is None


def test_pfz_available_is_carried_but_never_affects_score() -> None:
    pfz_favorable = PFZReference(status="available", value="favorable", source="incois-pfz-reference")
    pfz_unfavorable = PFZReference(status="available", value="unfavorable", source="incois-pfz-reference")

    result_favorable = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS,
        pfz_reference=pfz_favorable,
    )
    result_unfavorable = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS,
        pfz_reference=pfz_unfavorable,
    )

    # Same numeric inputs, different PFZ labels -> identical ORCA score.
    # This is the architecture.md §21 "hard discipline rule" made concrete:
    # PFZ is cited, never blended into ORCA's own arithmetic.
    assert result_favorable.score == result_unfavorable.score
    assert result_favorable.pfz_reference.value == "favorable"
    assert result_unfavorable.pfz_reference.value == "unfavorable"


def test_higher_risk_reduces_suitability() -> None:
    low_risk = evaluate_suitability(
        signal_score=0.5, risk_score=0.0, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS
    )
    high_risk = evaluate_suitability(
        signal_score=0.5, risk_score=1.0, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS
    )
    assert low_risk.score > high_risk.score


def test_closer_zone_increases_suitability() -> None:
    near = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=0.0, confidence=0.8, weights=WEIGHTS
    )
    far = evaluate_suitability(
        signal_score=0.5, risk_score=0.2, distance_to_zone_km=1000.0, confidence=0.8, weights=WEIGHTS
    )
    assert near.score > far.score


def test_score_bounded() -> None:
    result = evaluate_suitability(
        signal_score=1.0, risk_score=0.0, distance_to_zone_km=0.0, confidence=1.0, weights=WEIGHTS
    )
    assert 0.0 <= result.score <= 1.0


def test_rejects_out_of_range_signal_score() -> None:
    with pytest.raises(ValueError):
        evaluate_suitability(signal_score=1.5, risk_score=0.2, distance_to_zone_km=5.0, confidence=0.8, weights=WEIGHTS)


def test_rejects_negative_distance() -> None:
    with pytest.raises(ValueError):
        evaluate_suitability(signal_score=0.5, risk_score=0.2, distance_to_zone_km=-1.0, confidence=0.8, weights=WEIGHTS)


def test_determinism() -> None:
    results = {
        evaluate_suitability(
            signal_score=0.6, risk_score=0.3, distance_to_zone_km=12.0, confidence=0.7, weights=WEIGHTS
        ).score
        for _ in range(10)
    }
    assert len(results) == 1
