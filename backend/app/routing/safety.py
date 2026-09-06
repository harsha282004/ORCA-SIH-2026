"""Route-level safety classification — Phase 5 task §9/§11/§13.

Reuses the EXISTING deterministic Safety Guard (`app.policy.safety_guard
.evaluate_safety_guard`) and Decision Engine (`app.decision.engine
.make_decision`) verbatim — this module computes NO new risk/safety
formula. It only builds the route-shaped INPUTS those two functions
already expect, the same way `app.fishing.temporal` and
`app.api.v1.safety._evaluate_safety` each build their own
context-appropriate `SafetyFacts` rather than forcing every caller through
`derive_safety_facts`'s single-point-AgentResult shape (which a route,
spanning many sampled grid cells, does not have).

Precedence (task §6, unchanged, verbatim from architecture.md §23):

    has_boundary_violation        -> BLOCK_BOUNDARY   (structurally impossible here — see below)
    has_critical_missing_data     -> BLOCK_MISSING_DATA
    confidence < min_threshold    -> BLOCK_LOW_CONFIDENCE
    has_active_high_severity_advisory (a real DANGER/CRITICAL hazard near the route) -> BLOCK_HAZARD
    otherwise                     -> PASS

`has_boundary_violation` is always False here by construction, not by
omission: `app.routing.engine.calculate_route` raises `RouteReconstructionError`
if `validate_route_path` finds the reconstructed path crosses ANY
non-navigable (hard-geofenced) cell — a `RouteResult` object simply cannot
exist if it violated a hard geofence. `has_critical_missing_data` and the
confidence gate are likewise already enforced by
`validate_environmental_data_quality` BEFORE a `RouteResult` is created
(`RouteDataQualityError`) — so by the time this module runs, those two
facts are always False/passing too. The only fact this module genuinely
computes is hazard exposure, from Phase 4's own `hazards_near_route`.
"""
from __future__ import annotations

from app.decision.engine import make_decision
from app.decision.models import Decision
from app.hazard.models import Hazard
from app.policy.models import SafetyFacts, SafetyGuardResult
from app.policy.safety_guard import evaluate_safety_guard
from app.risk.config import RiskConfig
from app.risk.engine import RiskLevel, classify_risk_level
from app.routing.models import RouteResult


def evaluate_route_safety(
    route: RouteResult,
    *,
    hazards_near_route: list[Hazard],
    risk_config: RiskConfig,
    alternative_exists: bool = False,
) -> tuple[Decision, SafetyGuardResult, RiskLevel]:
    """Returns (decision, safety, risk_level) for ONE already-computed
    route. `risk_level` is classified from the route's MAXIMUM per-cell
    risk score (`RouteMetrics.max_risk_score`) — task §9/§10's own emphasis
    on "why is this route risky" is best served by the worst segment along
    it, not diluted by an average across many calm cells; `average_risk_score`
    remains separately available on `RouteMetrics` for the "typical
    conditions" question.
    """
    critical_hazard_active = any(h.severity in ("DANGER", "CRITICAL") for h in hazards_near_route)

    facts = SafetyFacts(
        has_boundary_violation=False,  # see module docstring — structurally guaranteed by calculate_route
        has_critical_missing_data=False,  # see module docstring — already gated before a RouteResult exists
        confidence=route.confidence,
        has_active_high_severity_advisory=critical_hazard_active,
    )
    safety = evaluate_safety_guard(facts, min_confidence_threshold=risk_config.safety.min_confidence_threshold)

    max_risk = route.metrics.max_risk_score if route.metrics.max_risk_score is not None else 0.0
    risk_level = classify_risk_level(max_risk, risk_config.risk_thresholds)

    decision = make_decision(
        risk_level=risk_level,
        risk_score=max_risk,
        confidence=route.confidence,
        min_confidence_threshold=risk_config.safety.min_confidence_threshold,
        safety_guard_result=safety,
        alternative_exists=alternative_exists,
    )

    return decision, safety, risk_level
