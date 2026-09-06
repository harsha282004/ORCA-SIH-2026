"""Phase 7 — conversational time-window/best-time (`_handle_temporal_window_query`
in `app.api.v1.query`). `evaluate_temporal_suitability` itself is real,
offline-tested with fake adapters in tests/fishing/test_temporal.py; here
it is monkeypatched (the function has no adapter-injection seam at this
call site — same pre-existing limitation `GET /fishing/temporal` has) so
this test targets the HANDLER's own selection/framing logic in isolation,
never live network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.api.v1.query as query_module
from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.evidence_explanation.models import ExplanationOutput
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.query_understanding.models import IntentResult
from app.fishing.models import FishingCandidate
from app.llm.fake import FakeLLMProvider
from app.orchestration.state import OrchestrationState

NOW = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)


def _candidate(*, ts, status, risk_score, risk_level, suitability_score, decision_outcome, safety_outcome="PASS") -> FishingCandidate:
    return FishingCandidate(
        latitude=12.8, longitude=74.2, status=status, risk_score=risk_score, risk_level=risk_level,
        suitability_score=suitability_score, suitability_category="HIGH" if suitability_score and suitability_score > 0.5 else "LOW",
        decision_outcome=decision_outcome, safety_outcome=safety_outcome, confidence=0.9, timestamp=ts,
        reason=None if status == "ranked" else "blocked",
    )


def _series() -> list[FishingCandidate]:
    return [
        _candidate(ts=NOW, status="ranked", risk_score=0.2, risk_level="LOW", suitability_score=0.6, decision_outcome="RECOMMEND"),
        _candidate(ts=NOW + timedelta(hours=1), status="ranked", risk_score=0.5, risk_level="MODERATE", suitability_score=0.8, decision_outcome="RECOMMEND_WITH_CAUTION"),
        _candidate(ts=NOW + timedelta(hours=2), status="avoid", risk_score=0.9, risk_level="HIGH", suitability_score=None, decision_outcome="NO_SAFE_RECOMMENDATION", safety_outcome="BLOCK_HAZARD"),
    ]


def _intent(*, intent_class, wants_temporal_window=True) -> IntentResult:
    return IntentResult(
        language="en", intent_class=intent_class, activity="fishing",
        location={"type": "named_place", "name": "Area A", "resolved_bbox": {"min_lat": 12.7, "min_lon": 74.0, "max_lat": 12.9, "max_lon": 74.3}},
        destination=None, time_window={"start": NOW.isoformat(), "end": (NOW + timedelta(hours=6)).isoformat()},
        objective="best time", constraints={}, requires_route=False, requires_pfz_reference=False, persona="fisherman",
        refers_to_prior=False, reference_type=None, wants_temporal_window=wants_temporal_window,
    )


def _evidence_agent() -> EvidenceExplanationAgent:
    return EvidenceExplanationAgent(llm_provider=FakeLLMProvider(structured_response=ExplanationOutput(rationale="Temporal explanation.")))


def _call(intent_class, monkeypatch, series=None):
    monkeypatch.setattr(query_module, "evaluate_temporal_suitability", lambda **kwargs: series if series is not None else _series())
    state = OrchestrationState(query="best time?", intent=_intent(intent_class=intent_class), language="en", latitude=12.8, longitude=74.2)
    return query_module._handle_temporal_window_query(final_state=state, gis_agent=GISGeofencingAgent(), evidence_agent=_evidence_agent())


def test_safety_check_picks_lowest_risk_safe_hour(monkeypatch) -> None:
    response = _call("safety_check", monkeypatch)
    assert response is not None
    assert response.data["temporal"]["best_time_index"] == 0  # risk 0.2 < 0.5, hour 2 is blocked
    assert response.data["decision"]["outcome"] == "RECOMMEND"


def test_zone_recommendation_picks_highest_suitability_safe_hour(monkeypatch) -> None:
    response = _call("zone_recommendation", monkeypatch)
    assert response is not None
    assert response.data["temporal"]["best_time_index"] == 1  # suitability 0.8 > 0.6, hour 2 excluded (blocked)


def test_all_hours_blocked_returns_honest_no_recommendation(monkeypatch) -> None:
    blocked_series = [_candidate(ts=NOW, status="avoid", risk_score=0.95, risk_level="HIGH", suitability_score=None, decision_outcome="NO_SAFE_RECOMMENDATION", safety_outcome="BLOCK_HAZARD")]
    response = _call("safety_check", monkeypatch, series=blocked_series)
    assert response.data["temporal"]["best_time_index"] is None
    assert "decision" not in response.data


def test_temporal_response_discloses_cyclone_and_lightning_limitations(monkeypatch) -> None:
    response = _call("safety_check", monkeypatch)
    limitations = " ".join(response.data["temporal"]["limitations"])
    assert "cyclone" in limitations.lower()
    assert "lightning" in limitations.lower()


def test_series_preserves_real_distinct_timestamps(monkeypatch) -> None:
    response = _call("safety_check", monkeypatch)
    timestamps = [row["timestamp"] for row in response.data["temporal"]["series"]]
    assert len(set(timestamps)) == 3
