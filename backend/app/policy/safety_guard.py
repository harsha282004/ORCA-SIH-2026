"""Policy & Safety Guard — architecture.md §23.

A real, testable, deterministic function — not documentation. The LLM
cannot override any of this: it never sees these facts before this
function runs, and nothing downstream is permitted to second-guess its
outcome.

Precedence is taken verbatim from architecture.md §23's own pseudocode
(not re-derived), in this exact order:

    1. has_boundary_violation           -> BLOCK_BOUNDARY
    2. has_critical_missing_data        -> BLOCK_MISSING_DATA
    3. confidence < min_confidence_threshold -> BLOCK_LOW_CONFIDENCE
    4. has_active_high_severity_advisory -> BLOCK_HAZARD
    5. otherwise                        -> PASS

Note this differs from a hazard-second ordering one might expect from the
architecture's own prose summary elsewhere in the document — the code
block in §23 is unambiguous and is treated as authoritative here, per the
project rule that the architecture document is the frozen single source
of truth.
"""
from __future__ import annotations

from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.gis.geofence import GeofenceCheckResult
from app.models.contracts import AgentResult
from app.policy.models import SafetyFacts, SafetyGuardResult


def derive_safety_facts(
    *,
    weather: AgentResult | None,
    marine: AgentResult | None,
    boundary_check: GeofenceCheckResult | None,
    risk_suitability: RiskSuitabilityResult | None,
) -> SafetyFacts:
    """Builds `SafetyFacts` from the raw pipeline state — the exact
    derivation `OrchestrationNodes.safety_guard` uses for a live query,
    extracted here so the Scenario Engine (architecture.md §32, "re-run
    ... Safety Guard on the perturbed state") can re-derive facts for a
    perturbed re-scoring without a second, drifting copy of this logic.
    """
    has_boundary_violation = bool(boundary_check and boundary_check.blocked)
    has_critical_missing_data = (
        weather is None
        or marine is None
        or boundary_check is None
        or risk_suitability is None
        or risk_suitability.status == "insufficient_data"
    )
    confidence = risk_suitability.confidence if risk_suitability and risk_suitability.status == "ok" else 0.0
    # architecture.md §29: no official advisory ingestion exists yet — always
    # False, an honest, documented scope limitation, never a fabricated
    # "no hazard" claim about a data source that was never actually checked.
    has_active_high_severity_advisory = False

    return SafetyFacts(
        has_boundary_violation=has_boundary_violation,
        has_critical_missing_data=has_critical_missing_data,
        confidence=confidence,
        has_active_high_severity_advisory=has_active_high_severity_advisory,
    )


def evaluate_safety_guard(facts: SafetyFacts, *, min_confidence_threshold: float) -> SafetyGuardResult:
    if not (0.0 <= min_confidence_threshold <= 1.0):
        raise ValueError(f"min_confidence_threshold must be in [0, 1], got {min_confidence_threshold}")

    if facts.has_boundary_violation:
        return SafetyGuardResult(
            outcome="BLOCK_BOUNDARY",
            reason="the point/route falls inside a hard geofence (land, protected area, "
            "international boundary, or an active restricted zone)",
            triggered_rule="has_boundary_violation",
        )

    if facts.has_critical_missing_data:
        return SafetyGuardResult(
            outcome="BLOCK_MISSING_DATA",
            reason="one or more factors required for this query could not be resolved at all",
            triggered_rule="has_critical_missing_data",
        )

    if facts.confidence < min_confidence_threshold:
        return SafetyGuardResult(
            outcome="BLOCK_LOW_CONFIDENCE",
            reason=f"confidence {facts.confidence:.3f} is below the configured minimum "
            f"{min_confidence_threshold:.3f}",
            triggered_rule="confidence_below_min_confidence_threshold",
        )

    if facts.has_active_high_severity_advisory:
        return SafetyGuardResult(
            outcome="BLOCK_HAZARD",
            reason="an active official advisory at HIGH severity applies to this area/time",
            triggered_rule="has_active_high_severity_advisory",
        )

    return SafetyGuardResult(outcome="PASS", reason="no blocking condition triggered", triggered_rule="none")
