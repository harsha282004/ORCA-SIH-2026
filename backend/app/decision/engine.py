"""The deterministic Decision Engine — architecture.md §24.

    LOW risk      + sufficient confidence + no blocking hazard -> RECOMMEND
    MODERATE risk + sufficient confidence + no blocking hazard -> RECOMMEND_WITH_CAUTION
    HIGH risk     -> PROVIDE_ALTERNATIVES (if a safe alternative exists)
                  -> NO_SAFE_RECOMMENDATION (otherwise)
    Any Safety Guard BLOCK_* outcome                           -> NO_SAFE_RECOMMENDATION

This is implemented as a deterministic function of
{risk_level, confidence, safety_guard.outcome, alternative_exists} exactly
as architecture.md §24 specifies — the Decision Engine chooses the final
decision; the LLM never does. No natural-language explanation is produced
here.
"""
from __future__ import annotations

from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.decision.models import Decision
from app.policy.models import SafetyGuardResult
from app.risk.engine import RiskLevel


def risk_inputs_for_decision(risk_suitability: RiskSuitabilityResult | None) -> tuple[RiskLevel, float, float]:
    """Derives `(risk_level, risk_score, confidence)` for `make_decision`
    from a `RiskSuitabilityResult` — shared by the live orchestration
    `decision` node and the Scenario Engine (architecture.md §32) so both
    use identically-derived conservative placeholders when
    `risk_suitability` isn't "ok", rather than two independently-maintained
    copies of this fallback.
    """
    if risk_suitability is not None and risk_suitability.status == "ok":
        return risk_suitability.risk_result.level, risk_suitability.risk_result.score, risk_suitability.confidence
    # Conservative placeholders — never actually determinative, since the
    # Safety Guard's has_critical_missing_data always fires whenever
    # risk_suitability isn't "ok", and make_decision maps any non-PASS
    # safety outcome to NO_SAFE_RECOMMENDATION regardless of these values.
    return "HIGH", 1.0, 0.0


def make_decision(
    *,
    risk_level: RiskLevel,
    risk_score: float,
    confidence: float,
    min_confidence_threshold: float,
    safety_guard_result: SafetyGuardResult,
    alternative_exists: bool = False,
) -> Decision:
    if not (0.0 <= risk_score <= 1.0):
        raise ValueError(f"risk_score must be in [0, 1], got {risk_score}")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")

    if safety_guard_result.outcome != "PASS":
        return Decision(
            outcome="NO_SAFE_RECOMMENDATION",
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            safety_guard_outcome=safety_guard_result.outcome,
            reason=f"Safety Guard blocked this query: {safety_guard_result.outcome} — {safety_guard_result.reason}",
        )

    sufficient_confidence = confidence >= min_confidence_threshold

    if risk_level == "LOW" and sufficient_confidence:
        return Decision(
            outcome="RECOMMEND",
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            safety_guard_outcome=safety_guard_result.outcome,
            reason="risk is LOW and confidence is sufficient",
        )

    if risk_level == "MODERATE" and sufficient_confidence:
        return Decision(
            outcome="RECOMMEND_WITH_CAUTION",
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            safety_guard_outcome=safety_guard_result.outcome,
            reason="risk is MODERATE and confidence is sufficient; proceed with caution",
        )

    if risk_level == "HIGH":
        if alternative_exists:
            return Decision(
                outcome="PROVIDE_ALTERNATIVES",
                risk_level=risk_level,
                risk_score=risk_score,
                confidence=confidence,
                safety_guard_outcome=safety_guard_result.outcome,
                reason="risk is HIGH for the requested location, but a safer alternative candidate exists",
                alternative_used=True,
            )
        return Decision(
            outcome="NO_SAFE_RECOMMENDATION",
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            safety_guard_outcome=safety_guard_result.outcome,
            reason="risk is HIGH and no safe alternative candidate exists",
        )

    # risk_level in {LOW, MODERATE} but confidence is insufficient. The
    # Safety Guard should already have produced BLOCK_LOW_CONFIDENCE before
    # this function is ever reached with safety_guard_result.outcome ==
    # "PASS" — this branch is a defensive fallback for callers that invoke
    # the Decision Engine directly without first running the Safety Guard,
    # never a path this system's own pipeline is expected to take.
    return Decision(
        outcome="NO_SAFE_RECOMMENDATION",
        risk_level=risk_level,
        risk_score=risk_score,
        confidence=confidence,
        safety_guard_outcome=safety_guard_result.outcome,
        reason=f"risk is {risk_level} but confidence {confidence:.3f} is below the configured "
        f"minimum {min_confidence_threshold:.3f}",
    )
