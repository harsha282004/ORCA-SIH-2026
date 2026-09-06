"""Phase 6 — conversational follow-up reuse (`_handle_conversational_followup`
in `app.api.v1.query`). Pure unit tests: hand-built `OrchestrationState`/
`SessionState` objects, `FakeLLMProvider`-backed `EvidenceExplanationAgent`
— no live network, no graph invocation (that's covered separately by
tests/orchestration and tests/api/test_query.py's existing full-stack
tests).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.agents.query_understanding.models import IntentResult
from app.api.v1.query import _handle_conversational_followup
from app.llm.fake import FakeLLMProvider
from app.orchestration.state import OrchestrationState
from app.session.models import SessionState

NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)


def _evidence_agent(rationale: str = "Test explanation.") -> EvidenceExplanationAgent:
    return EvidenceExplanationAgent(llm_provider=FakeLLMProvider(structured_response=ExplanationOutput(rationale=rationale)))


def _intent(**overrides) -> IntentResult:
    defaults = dict(
        language="en", intent_class="route_planning", activity="fishing",
        location={"type": "named_place", "name": "Mangaluru", "resolved_bbox": {"min_lat": 12.7, "min_lon": 74.0, "max_lat": 12.9, "max_lon": 74.3}},
        destination=None,
        time_window={"start": NOW.isoformat(), "end": NOW.isoformat()},
        objective="test", constraints={}, requires_route=True, requires_pfz_reference=False, persona="fisherman",
        refers_to_prior=True, reference_type="same_query_different_param",
    )
    defaults.update(overrides)
    return IntentResult(**defaults)


ROUTE_A = {
    "label": "A", "latitude": 13.30, "longitude": 74.10, "distance_km": 60.2, "total_cost": 65.0,
    "risk_level": "LOW", "risk_score": 0.25, "confidence": 0.99, "decision_outcome": "RECOMMEND",
    "decision_reason": "risk is LOW", "safety_outcome": "PASS", "safety_reason": "no blocking condition", "hazard_count": 0,
}
ROUTE_B = {
    "label": "B", "latitude": 13.30, "longitude": 74.10, "distance_km": 69.2, "total_cost": 60.0,
    "risk_level": "LOW", "risk_score": 0.20, "confidence": 0.99, "decision_outcome": "RECOMMEND",
    "decision_reason": "risk is LOW", "safety_outcome": "PASS", "safety_reason": "no blocking condition", "hazard_count": 0,
}
CANDIDATE_A = {
    "label": "A", "latitude": 12.85, "longitude": 74.15, "risk_level": "MODERATE", "risk_score": 0.45,
    "suitability_score": 0.7, "suitability_category": "HIGH", "decision_outcome": "RECOMMEND_WITH_CAUTION",
    "safety_outcome": "PASS", "confidence": 0.95,
}
CANDIDATE_B = {
    "label": "B", "latitude": 12.90, "longitude": 74.20, "risk_level": "LOW", "risk_score": 0.15,
    "suitability_score": 0.6, "suitability_category": "MODERATE", "decision_outcome": "RECOMMEND",
    "safety_outcome": "PASS", "confidence": 0.95,
}


def test_returns_none_when_not_a_follow_up() -> None:
    state = OrchestrationState(query="x", intent=_intent(refers_to_prior=False))
    session = SessionState(last_route_options=[ROUTE_A, ROUTE_B])
    assert _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent()) is None


def test_returns_none_when_no_stored_context_exists() -> None:
    state = OrchestrationState(query="x", intent=_intent(selection_reference="alternative"))
    session = SessionState()  # nothing stored
    assert _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent()) is None


def test_route_alternative_follow_up_reuses_route_b_without_recomputation() -> None:
    state = OrchestrationState(query="What about the alternative?", intent=_intent(selection_reference="alternative"))
    session = SessionState(last_route_options=[ROUTE_A, ROUTE_B])

    response = _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent())

    assert response is not None
    assert response.data["reused_prior_result"] is True
    assert response.data["decision"]["risk_score"] == 0.20  # Route B's, not Route A's
    assert "69.2" in response.data["route_note"] or "69.2" in str(response.data.get("route_note"))
    assert response.provenance is not None
    assert response.provenance.route.distance_km == 69.2


def test_route_compare_follow_up_reuses_stored_comparison() -> None:
    state = OrchestrationState(query="Which one is safer?", intent=_intent(operation="compare"))
    session = SessionState(
        last_route_options=[ROUTE_A, ROUTE_B],
        last_route_comparison={"recommended_label": "B", "reason": "Route B has lower risk despite greater distance.", "generated_at": NOW.isoformat()},
    )

    response = _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent())

    assert response is not None
    assert response.data["route_comparison"]["recommended_label"] == "B"
    assert response.data["decision"]["risk_score"] == 0.20  # the recommended (B)'s risk score


def test_fishing_compare_follow_up_picks_lowest_risk_candidate() -> None:
    state = OrchestrationState(query="Which is safest?", intent=_intent(intent_class="zone_recommendation", operation="compare"))
    session = SessionState(last_fishing_candidates=[CANDIDATE_A, CANDIDATE_B])

    response = _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent())

    assert response is not None
    assert response.data["fishing_candidates"]["top"]["label"] == "B"  # lower risk_score (0.15 < 0.45)
    assert response.data["decision"]["risk_level"] == "LOW"
    assert response.data["reused_prior_result"] is True


def test_fishing_compare_excludes_blocked_candidates_from_the_pool() -> None:
    blocked = {**CANDIDATE_B, "label": "B", "risk_score": 0.05, "decision_outcome": "NO_SAFE_RECOMMENDATION"}
    state = OrchestrationState(query="Which is safest?", intent=_intent(intent_class="zone_recommendation", operation="compare"))
    session = SessionState(last_fishing_candidates=[CANDIDATE_A, blocked])

    response = _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent())

    # Even though "B" has a numerically lower risk_score, it's blocked —
    # the eligible pool must exclude it (task §6's "shorter/lower must not
    # win if unsafe" principle, applied to the reuse path too).
    assert response.data["fishing_candidates"]["top"]["label"] == "A"


def test_single_route_option_is_not_treated_as_having_an_alternative() -> None:
    state = OrchestrationState(query="What about the alternative?", intent=_intent(selection_reference="alternative"))
    session = SessionState(last_route_options=[ROUTE_A])  # only one route was ever generated
    assert _handle_conversational_followup(final_state=state, session=session, evidence_agent=_evidence_agent()) is None
