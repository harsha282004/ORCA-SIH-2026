from datetime import datetime, timezone

from app.agents.evidence_explanation.template import build_templated_explanation
from app.decision.models import Decision
from app.policy.models import SafetyGuardResult
from app.provenance.models import DecisionProvenanceGraph, GeographicProvenance, RiskProvenance


def test_no_decision_yields_an_insufficient_information_message() -> None:
    provenance = DecisionProvenanceGraph(query_id="q1", generated_at=datetime.now(timezone.utc))
    text = build_templated_explanation(provenance)
    assert "insufficient information" in text.lower()


def test_blocked_decision_never_claims_safety_in_the_template() -> None:
    decision = Decision(
        outcome="NO_SAFE_RECOMMENDATION",
        risk_level="HIGH",
        risk_score=0.9,
        confidence=0.9,
        safety_guard_outcome="BLOCK_BOUNDARY",
        reason="Safety Guard blocked this query: BLOCK_BOUNDARY",
    )
    safety = SafetyGuardResult(outcome="BLOCK_BOUNDARY", reason="inside a hard geofence", triggered_rule="has_boundary_violation")
    provenance = DecisionProvenanceGraph(
        query_id="q1", decision=decision, safety=safety, generated_at=datetime.now(timezone.utc)
    )
    text = build_templated_explanation(provenance)
    assert "NO_SAFE_RECOMMENDATION" in text
    assert "not able to provide a safe recommendation" in text
    assert "is safe" not in text.lower()


def test_every_number_in_the_template_traces_to_provenance() -> None:
    decision = Decision(
        outcome="RECOMMEND", risk_level="LOW", risk_score=0.21, confidence=0.95,
        safety_guard_outcome="PASS", reason="risk is LOW and confidence is sufficient",
    )
    risk = RiskProvenance(factors=[], score=0.21, level="LOW")
    provenance = DecisionProvenanceGraph(query_id="q1", decision=decision, risk=risk, generated_at=datetime.now(timezone.utc))
    text = build_templated_explanation(provenance)
    assert "0.21" in text
