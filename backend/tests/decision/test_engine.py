import pytest

from app.decision.engine import make_decision
from app.policy.models import SafetyGuardResult

MIN_CONFIDENCE = 0.5


def guard(outcome: str = "PASS") -> SafetyGuardResult:
    return SafetyGuardResult(outcome=outcome, reason="test", triggered_rule="test")


def test_recommend_when_low_risk_and_sufficient_confidence() -> None:
    decision = make_decision(
        risk_level="LOW", risk_score=0.2, confidence=0.8, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard("PASS"),
    )
    assert decision.outcome == "RECOMMEND"


def test_recommend_with_caution_when_moderate_risk() -> None:
    decision = make_decision(
        risk_level="MODERATE", risk_score=0.5, confidence=0.8, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard("PASS"),
    )
    assert decision.outcome == "RECOMMEND_WITH_CAUTION"


def test_provide_alternatives_when_high_risk_and_alternative_exists() -> None:
    decision = make_decision(
        risk_level="HIGH", risk_score=0.9, confidence=0.8, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard("PASS"), alternative_exists=True,
    )
    assert decision.outcome == "PROVIDE_ALTERNATIVES"
    assert decision.alternative_used is True


def test_no_safe_recommendation_when_high_risk_and_no_alternative() -> None:
    decision = make_decision(
        risk_level="HIGH", risk_score=0.9, confidence=0.8, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard("PASS"), alternative_exists=False,
    )
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"


@pytest.mark.parametrize(
    "blocked_outcome", ["BLOCK_BOUNDARY", "BLOCK_MISSING_DATA", "BLOCK_LOW_CONFIDENCE", "BLOCK_HAZARD"]
)
def test_any_safety_guard_block_forces_no_safe_recommendation(blocked_outcome: str) -> None:
    # Even a LOW risk, high-confidence, alternative-available case must
    # still be NO_SAFE_RECOMMENDATION if the Safety Guard blocked it —
    # the LLM (and nothing else) can override this.
    decision = make_decision(
        risk_level="LOW", risk_score=0.1, confidence=0.99, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard(blocked_outcome), alternative_exists=True,
    )
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"
    assert decision.safety_guard_outcome == blocked_outcome


def test_low_risk_but_below_min_confidence_is_not_recommend() -> None:
    """architecture.md Phase 2 spec §23: LOW risk + very low confidence
    must not automatically mean safe. In the real pipeline the Safety
    Guard would already have produced BLOCK_LOW_CONFIDENCE before this is
    reached; this test exercises the Decision Engine's own defensive
    fallback for a caller that (incorrectly) calls it directly with a
    stale PASS despite insufficient confidence.
    """
    decision = make_decision(
        risk_level="LOW", risk_score=0.1, confidence=0.1, min_confidence_threshold=MIN_CONFIDENCE,
        safety_guard_result=guard("PASS"),
    )
    assert decision.outcome == "NO_SAFE_RECOMMENDATION"


def test_rejects_invalid_risk_score() -> None:
    with pytest.raises(ValueError):
        make_decision(
            risk_level="LOW", risk_score=1.5, confidence=0.8, min_confidence_threshold=MIN_CONFIDENCE,
            safety_guard_result=guard("PASS"),
        )


def test_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        make_decision(
            risk_level="LOW", risk_score=0.2, confidence=-0.1, min_confidence_threshold=MIN_CONFIDENCE,
            safety_guard_result=guard("PASS"),
        )


def test_determinism() -> None:
    outcomes = {
        make_decision(
            risk_level="MODERATE", risk_score=0.5, confidence=0.7, min_confidence_threshold=MIN_CONFIDENCE,
            safety_guard_result=guard("PASS"),
        ).outcome
        for _ in range(10)
    }
    assert len(outcomes) == 1
