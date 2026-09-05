"""Evidence & Explanation Agent — architecture.md §12 mechanism #5 (grounding
check -> regenerate once -> template fallback) and Phase 5 task spec §20
(never claim safety for a NO_SAFE_RECOMMENDATION decision). Every test uses
`FakeLLMProvider`; zero network/API-key dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.decision.models import Decision
from app.llm.base import LLMResponseError
from app.llm.fake import FakeLLMProvider
from app.policy.models import SafetyGuardResult
from app.provenance.models import DecisionProvenanceGraph, RiskProvenance

NOW = datetime.now(timezone.utc)

_RECOMMEND_DECISION = Decision(
    outcome="RECOMMEND", risk_level="LOW", risk_score=0.21, confidence=0.95,
    safety_guard_outcome="PASS", reason="risk is LOW and confidence is sufficient",
)
_BLOCKED_DECISION = Decision(
    outcome="NO_SAFE_RECOMMENDATION", risk_level="HIGH", risk_score=0.9, confidence=0.9,
    safety_guard_outcome="BLOCK_BOUNDARY", reason="Safety Guard blocked this query: BLOCK_BOUNDARY",
)
_BLOCKED_SAFETY = SafetyGuardResult(outcome="BLOCK_BOUNDARY", reason="inside a hard geofence", triggered_rule="has_boundary_violation")


def _provenance(decision: Decision, *, safety: SafetyGuardResult | None = None) -> DecisionProvenanceGraph:
    risk = RiskProvenance(factors=[], score=decision.risk_score, level=decision.risk_level)
    return DecisionProvenanceGraph(query_id="q1", decision=decision, risk=risk, safety=safety, generated_at=NOW)


def test_grounded_output_is_accepted_on_the_first_attempt() -> None:
    llm = FakeLLMProvider(structured_response=ExplanationOutput(rationale="Risk score is 0.21, which is LOW."))
    agent = EvidenceExplanationAgent(llm_provider=llm)

    result = agent.explain(provenance=_provenance(_RECOMMEND_DECISION), language="en", persona="fisherman")

    assert result.grounded is True
    assert result.used_fallback_template is False
    assert len(llm.calls) == 1


def test_fabricated_number_triggers_one_regeneration_then_succeeds() -> None:
    bad = ExplanationOutput(rationale="Risk score is 7.00, extremely dangerous.")
    good = ExplanationOutput(rationale="Risk score is 0.21, which is LOW.")
    llm = FakeLLMProvider()
    responses = iter([bad, good])
    llm.generate_structured = lambda **kwargs: next(responses)  # type: ignore[method-assign]

    agent = EvidenceExplanationAgent(llm_provider=llm)
    result = agent.explain(provenance=_provenance(_RECOMMEND_DECISION), language="en", persona="fisherman")

    assert result.rationale == good.rationale
    assert result.used_fallback_template is False


def test_persistently_ungrounded_output_falls_back_to_template() -> None:
    llm = FakeLLMProvider(structured_response=ExplanationOutput(rationale="Risk score is 7.00, extremely dangerous."))
    agent = EvidenceExplanationAgent(llm_provider=llm)

    result = agent.explain(provenance=_provenance(_RECOMMEND_DECISION), language="en", persona="fisherman")

    assert result.used_fallback_template is True
    assert result.grounded is True  # the template itself is always grounded by construction
    assert len(llm.calls) == 2  # generate once, regenerate once, then give up


def test_llm_cannot_claim_safety_for_a_no_safe_recommendation_decision() -> None:
    llm = FakeLLMProvider(structured_response=ExplanationOutput(rationale="It is safe to go fishing here."))
    agent = EvidenceExplanationAgent(llm_provider=llm)

    result = agent.explain(
        provenance=_provenance(_BLOCKED_DECISION, safety=_BLOCKED_SAFETY), language="en", persona="fisherman"
    )

    assert result.used_fallback_template is True
    assert "is safe" not in result.rationale.lower()
    assert "NO_SAFE_RECOMMENDATION" in result.rationale


def test_llm_provider_failure_falls_back_to_template_immediately() -> None:
    llm = FakeLLMProvider(fail_with=LLMResponseError("provider down"))
    agent = EvidenceExplanationAgent(llm_provider=llm)

    result = agent.explain(provenance=_provenance(_RECOMMEND_DECISION), language="en", persona="fisherman")

    assert result.used_fallback_template is True
    assert "0.21" in result.rationale


def test_explanation_result_always_carries_the_full_provenance() -> None:
    llm = FakeLLMProvider(structured_response=ExplanationOutput(rationale="Risk score is 0.21, which is LOW."))
    agent = EvidenceExplanationAgent(llm_provider=llm)

    provenance = _provenance(_RECOMMEND_DECISION)
    result = agent.explain(provenance=provenance, language="en", persona="fisherman")

    assert result.provenance == provenance
