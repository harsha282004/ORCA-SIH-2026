import pytest

from app.policy.models import SafetyFacts
from app.policy.safety_guard import evaluate_safety_guard

MIN_CONFIDENCE = 0.5


def facts(**overrides) -> SafetyFacts:
    base = dict(
        has_boundary_violation=False,
        has_critical_missing_data=False,
        confidence=0.9,
        has_active_high_severity_advisory=False,
    )
    base.update(overrides)
    return SafetyFacts(**base)


def test_pass_when_nothing_triggers() -> None:
    result = evaluate_safety_guard(facts(), min_confidence_threshold=MIN_CONFIDENCE)
    assert result.outcome == "PASS"


def test_block_boundary() -> None:
    result = evaluate_safety_guard(facts(has_boundary_violation=True), min_confidence_threshold=MIN_CONFIDENCE)
    assert result.outcome == "BLOCK_BOUNDARY"
    assert result.triggered_rule == "has_boundary_violation"


def test_block_missing_data() -> None:
    result = evaluate_safety_guard(facts(has_critical_missing_data=True), min_confidence_threshold=MIN_CONFIDENCE)
    assert result.outcome == "BLOCK_MISSING_DATA"


def test_block_low_confidence() -> None:
    result = evaluate_safety_guard(facts(confidence=0.1), min_confidence_threshold=MIN_CONFIDENCE)
    assert result.outcome == "BLOCK_LOW_CONFIDENCE"


def test_confidence_exactly_at_threshold_passes() -> None:
    # `< min_confidence_threshold` per architecture.md §23 — equal to the
    # threshold must NOT block.
    result = evaluate_safety_guard(facts(confidence=MIN_CONFIDENCE), min_confidence_threshold=MIN_CONFIDENCE)
    assert result.outcome == "PASS"


def test_block_hazard() -> None:
    result = evaluate_safety_guard(
        facts(has_active_high_severity_advisory=True), min_confidence_threshold=MIN_CONFIDENCE
    )
    assert result.outcome == "BLOCK_HAZARD"


def test_precedence_boundary_beats_everything() -> None:
    """architecture.md §23's literal code order: boundary is checked
    first — a boundary violation must win even if missing data, low
    confidence, AND an active hazard are all also true.
    """
    result = evaluate_safety_guard(
        facts(
            has_boundary_violation=True,
            has_critical_missing_data=True,
            confidence=0.0,
            has_active_high_severity_advisory=True,
        ),
        min_confidence_threshold=MIN_CONFIDENCE,
    )
    assert result.outcome == "BLOCK_BOUNDARY"


def test_precedence_missing_data_beats_confidence_and_hazard() -> None:
    result = evaluate_safety_guard(
        facts(has_critical_missing_data=True, confidence=0.0, has_active_high_severity_advisory=True),
        min_confidence_threshold=MIN_CONFIDENCE,
    )
    assert result.outcome == "BLOCK_MISSING_DATA"


def test_precedence_low_confidence_beats_hazard() -> None:
    """architecture.md §23's code checks confidence BEFORE the hazard
    advisory — a genuinely surprising ordering (hazard is last, not
    second), but it is what the frozen architecture's own pseudocode says,
    so it is what this implementation follows.
    """
    result = evaluate_safety_guard(
        facts(confidence=0.0, has_active_high_severity_advisory=True), min_confidence_threshold=MIN_CONFIDENCE
    )
    assert result.outcome == "BLOCK_LOW_CONFIDENCE"


def test_invalid_min_confidence_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_safety_guard(facts(), min_confidence_threshold=1.5)


def test_determinism() -> None:
    results = {evaluate_safety_guard(facts(confidence=0.42), min_confidence_threshold=MIN_CONFIDENCE).outcome for _ in range(10)}
    assert len(results) == 1
