"""Deterministic route comparison — Phase 5 task §14.

Ranks already-evaluated `RankedRoute`s (each already carries a real
`Decision`/`SafetyGuardResult`/`risk_level` from `app.routing.safety
.evaluate_route_safety` — this module computes NO risk/safety itself, only
a preference ordering over values that already exist) using the SAME
precedence the whole project applies everywhere else (task §6, §13):

    SAFETY (Safety Guard outcome != PASS)      -> never preferred
    DECISION (NO_SAFE_RECOMMENDATION)          -> never preferred
    RISK LEVEL (HIGH worse than MODERATE worse than LOW)
    RISK SCORE (lower is better, tie-break within the same level)
    DISTANCE (shorter is better, tie-break only after all of the above)

A shorter/cheaper route NEVER outranks a safer one — task §6's "a
shorter route must NOT win if it is unsafe," enforced by construction: the
sort key's first two components are safety-derived, distance is the LAST
tie-breaker, never the primary key.
"""
from __future__ import annotations

from app.routing.models import RankedRoute, RouteComparisonResult

_DECISION_RANK = {
    "RECOMMEND": 0,
    "RECOMMEND_WITH_CAUTION": 1,
    "PROVIDE_ALTERNATIVES": 2,
    "NO_SAFE_RECOMMENDATION": 3,
}
_RISK_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}


def _sort_key(ranked: RankedRoute) -> tuple:
    safety_blocked = 1 if ranked.safety.outcome != "PASS" else 0
    return (
        safety_blocked,
        _DECISION_RANK.get(ranked.decision.outcome, 99),
        _RISK_RANK.get(ranked.risk_level, 99),
        ranked.decision.risk_score,
        ranked.route.metrics.total_distance_km,
    )


def compare_routes(routes: list[RankedRoute]) -> RouteComparisonResult:
    if not routes:
        return RouteComparisonResult(routes=[], recommended_label=None, reason="no candidate routes were generated")

    best = min(routes, key=_sort_key)

    if best.safety.outcome != "PASS" or best.decision.outcome == "NO_SAFE_RECOMMENDATION":
        # Every candidate is blocked — never recommend the "least bad" one
        # as if it were safe (task §22/§30's "missing/unsafe must never
        # become safe" principle applied to route comparison).
        return RouteComparisonResult(
            routes=routes,
            recommended_label=None,
            reason=(
                "none of the generated route options pass ORCA's deterministic safety checks — "
                f"the best available option ({best.label}) is still {best.decision.outcome}: {best.decision.reason}"
            ),
        )

    others = [r for r in routes if r.label != best.label]
    if not others:
        reason = (
            f"Route {best.label} is the only deterministically generated option "
            f"({best.route.metrics.total_distance_km:.1f} km, {best.risk_level} risk, {best.decision.outcome})."
        )
    else:
        comparisons = ", ".join(
            f"Route {o.label} ({o.route.metrics.total_distance_km:.1f} km, {o.risk_level} risk, {o.decision.outcome})"
            for o in others
        )
        reason = (
            f"Route {best.label} is recommended: {best.risk_level} risk "
            f"(max risk score {best.decision.risk_score:.3f}) over {best.route.metrics.total_distance_km:.1f} km, "
            f"{best.decision.outcome}. Compared against {comparisons} — lower deterministic risk takes precedence "
            "over shorter distance."
        )

    return RouteComparisonResult(routes=routes, recommended_label=best.label, reason=reason)
