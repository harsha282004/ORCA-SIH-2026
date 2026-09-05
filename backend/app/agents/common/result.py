"""Builds a typed `app.models.contracts.AgentResult` from a batch of
NormalizedObservation — the single place every agent constructs its
return value, so the confidence formula (architecture.md §22, reused
verbatim from Phase 2 — never a second formula) and temporal-validity
rollup (§17) are computed identically across all three agents.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.fabric.temporal import freshness_seconds
from app.models.contracts import AgentResult, Mode, NormalizedObservation, SourceTier, TemporalValidityStatus
from app.reasoning.confidence import ConfidenceInputs, compute_confidence
from app.risk.config import get_risk_config

_SEVERITY_ORDER: dict[TemporalValidityStatus, int] = {
    "VALID": 0,
    "STALE": 1,
    "EXPIRED": 2,
    "INVALID_TIMESTAMP": 3,
    "MISSING_TIMESTAMP": 4,
}


def worst_temporal_validity_status(statuses: list[TemporalValidityStatus]) -> TemporalValidityStatus:
    """The most severe status among `statuses` — public so callers combining
    multiple AgentResults (e.g. the routing environmental provider, across
    several sample sites) can roll them up with the same severity order,
    without re-deriving it.
    """
    if not statuses:
        return "MISSING_TIMESTAMP"
    return max(statuses, key=lambda status: _SEVERITY_ORDER[status])


def worst_temporal_validity(observations: list[NormalizedObservation]) -> TemporalValidityStatus:
    """The most severe status across a batch of observations — a single
    stale/expired/missing factor makes the whole result's headline status
    reflect that, never averaged away (a conservative, safety-first rollup).
    """
    if not observations:
        return "MISSING_TIMESTAMP"
    return worst_temporal_validity_status([o.temporal_validity for o in observations])


def rollup_confidence(
    observations: list[NormalizedObservation],
    *,
    requested_time: datetime,
    max_staleness: timedelta,
    expected_parameter_count: int,
) -> float:
    """architecture.md §22: confidence = 0.40*freshness + 0.35*completeness
    + 0.25*agreement — Phase 2's exact weights, reused via
    app.reasoning.confidence, not recomputed with a second formula.
    """
    if not observations:
        return 0.0

    newest_retrieved_at = max(o.retrieved_at for o in observations)
    age_seconds = freshness_seconds(newest_retrieved_at, requested_time)
    max_staleness_seconds = max_staleness.total_seconds()
    freshness = max(0.0, min(1.0, 1.0 - (age_seconds / max_staleness_seconds))) if max_staleness_seconds > 0 else 0.0

    present = sum(1 for o in observations if not o.quality.is_missing)
    completeness = min(1.0, present / expected_parameter_count) if expected_parameter_count > 0 else 0.0

    # No second independent source is integrated yet to disagree with —
    # this is "no known disagreement", not a claim of verified cross-
    # source agreement (architecture.md §19/§20 evidence arbitration and
    # conflict resolution remain unimplemented — Phase 4+ scope note, see
    # docs/data_agents.md).
    agreement = 1.0

    weights = get_risk_config().confidence_weights
    inputs = ConfidenceInputs(freshness=freshness, completeness=completeness, agreement=agreement)
    return compute_confidence(inputs, weights)


def build_agent_result(
    *,
    observations: list[NormalizedObservation],
    mode: Mode,
    latitude: float,
    longitude: float,
    requested_time: datetime,
    max_staleness: timedelta,
    expected_parameter_count: int,
    source_tier_override: SourceTier | None = None,
    status: str = "ok",
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> AgentResult:
    temporal_validity_status = worst_temporal_validity(observations)
    confidence = rollup_confidence(
        observations,
        requested_time=requested_time,
        max_staleness=max_staleness,
        expected_parameter_count=expected_parameter_count,
    )
    source_tier: SourceTier = source_tier_override or (observations[0].source_tier if observations else "live")

    data = {obs.parameter: obs.value for obs in observations if not obs.quality.is_missing}

    evidence = []
    for obs in observations:
        if obs.quality.is_missing:
            continue
        try:
            evidence.append(obs.to_evidence(confidence=confidence))
        except ValueError:
            continue  # an observation missing a resolved timestamp cannot become Evidence — skip, don't crash

    valid_froms = [obs.valid_from for obs in observations if obs.valid_from is not None]
    valid_tos = [obs.valid_to for obs in observations if obs.valid_to is not None]

    return AgentResult(
        status=status,
        data=data,
        evidence=evidence,
        confidence=confidence,
        source_tier=source_tier,
        timestamp=requested_time,
        spatial_extent={"type": "Point", "coordinates": [longitude, latitude]},
        temporal_validity={
            "valid_from": min(valid_froms).isoformat() if valid_froms else None,
            "valid_to": max(valid_tos).isoformat() if valid_tos else None,
            "is_forecast": all(obs.is_forecast for obs in observations) if observations else False,
        },
        warnings=warnings or [],
        errors=errors or [],
        mode=mode,
        temporal_validity_status=temporal_validity_status,
    )


def build_failed_agent_result(*, mode: Mode, latitude: float, longitude: float, requested_time: datetime, errors: list[str]) -> AgentResult:
    """A structured failure — architecture.md §16: never fabricate data
    when no acceptable source exists.
    """
    return AgentResult(
        status="failed",
        data={},
        evidence=[],
        confidence=0.0,
        source_tier="live",
        timestamp=requested_time,
        spatial_extent={"type": "Point", "coordinates": [longitude, latitude]},
        temporal_validity={"valid_from": None, "valid_to": None, "is_forecast": False},
        errors=errors,
        mode=mode,
        temporal_validity_status="MISSING_TIMESTAMP",
    )
