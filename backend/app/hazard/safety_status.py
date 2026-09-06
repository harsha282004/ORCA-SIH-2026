"""Marine Safety Status — Phase 4 §16.

A presentation-layer derivation over EXISTING deterministic outputs
(Decision Engine outcome, Risk Engine level, real detected hazards) — the
same "classify an existing value into a display band" pattern
`app.risk.engine.classify_risk_level` and `app.suitability.engine
.classify_suitability_category` already use. This module computes NO risk,
NO suitability, NO safety-guard outcome itself; it only combines already-
computed values (plus, critically, the presence of UNAVAILABLE critical
sources) into one MarineSafetyLevel — task §30's explicit "missing data
must never silently become SAFE" requirement enforced right here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.decision.models import Decision
from app.hazard.models import Hazard, HazardSourceStatus, MarineSafetyLevel, MarineSafetyStatus
from app.policy.models import SafetyGuardResult


def classify_safety_status(
    *,
    decision: Decision | None,
    safety: SafetyGuardResult | None,
    hazards: list[Hazard],
    unavailable_sources: list[HazardSourceStatus],
) -> tuple[MarineSafetyLevel, str]:
    if decision is None or safety is None:
        return "UNKNOWN", "the deterministic Risk/Safety pipeline could not complete for this location/time"

    critical_hazard = any(h.severity in ("DANGER", "CRITICAL") for h in hazards)
    warning_hazard = any(h.severity == "WARNING" for h in hazards)
    advisory_hazard = any(h.severity == "ADVISORY" for h in hazards)

    if decision.outcome == "NO_SAFE_RECOMMENDATION" or critical_hazard:
        reason = safety.reason if safety.outcome != "PASS" else "a DANGER/CRITICAL hazard is active for this location"
        return "DANGER", reason

    if decision.outcome == "PROVIDE_ALTERNATIVES" or decision.risk_level == "HIGH" or warning_hazard:
        return "WARNING", decision.reason if decision.outcome == "PROVIDE_ALTERNATIVES" else "elevated risk or an active WARNING-level hazard"

    # A critical unavailable source (cyclone check failed, e.g.) means the
    # system genuinely does not know whether a DANGER-level condition
    # exists — this must never be reported as SAFE just because nothing
    # else flagged a problem (task §30's core requirement).
    if any(s.status == "UNAVAILABLE" and s.hazard_type == "CYCLONE" for s in unavailable_sources):
        return "UNKNOWN", "cyclone hazard data could not be retrieved for this assessment — safety status is incomplete, not confirmed safe"

    if decision.outcome == "RECOMMEND_WITH_CAUTION" or decision.risk_level == "MODERATE" or advisory_hazard:
        return "CAUTION", decision.reason

    if decision.outcome == "RECOMMEND" and decision.risk_level == "LOW":
        return "SAFE", decision.reason

    return "UNKNOWN", "insufficient information to determine a confident safety status"


def build_marine_safety_status(
    *,
    risk_suitability: RiskSuitabilityResult | None,
    decision: Decision | None,
    safety: SafetyGuardResult | None,
    hazards: list[Hazard],
    unavailable_sources: list[HazardSourceStatus],
) -> MarineSafetyStatus:
    level, reason = classify_safety_status(decision=decision, safety=safety, hazards=hazards, unavailable_sources=unavailable_sources)
    risk_result = risk_suitability.risk_result if risk_suitability and risk_suitability.status == "ok" else None

    return MarineSafetyStatus(
        level=level,
        reason=reason,
        decision_outcome=decision.outcome if decision else None,
        safety_guard_outcome=safety.outcome if safety else None,
        risk_level=risk_result.level if risk_result else None,
        risk_score=risk_result.score if risk_result else None,
        confidence=risk_suitability.confidence if risk_suitability else None,
        hazards=hazards,
        unavailable_sources=unavailable_sources,
        generated_at=datetime.now(timezone.utc),
    )
