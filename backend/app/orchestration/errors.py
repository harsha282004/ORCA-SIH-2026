"""Shared node-failure helpers — Phase 5 task spec §17: "each node must
have explicit failure handling; a node's exception must never silently
skip the Safety Guard."

Every orchestration node function wraps its own domain logic in a
try/except that converts an *expected* failure (a downstream agent/engine
raising a documented exception) into a structured `AgentRunRecord` plus an
entry in `state.errors`, and returns normally so the graph keeps moving
towards the Safety Guard/Decision Engine — which are the components
responsible for turning "something is missing" into a safe outcome
(`BLOCK_MISSING_DATA`), never a node silently vanishing from the trace.
A genuinely unexpected exception (a programming error) is deliberately
NOT caught here — it propagates and fails the request loudly, per the
project's "fail loud on the unexpected, fail structured on the expected"
principle (confirmed against LangGraph's own default behavior, which does
not swallow node exceptions).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.provenance.models import AgentRunRecord


def failed_run_record(
    agent_name: str, *, started_at: datetime, error: str, source_tier: str | None = None
) -> AgentRunRecord:
    return AgentRunRecord(
        agent_name=agent_name,
        status="failed",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        source_tier=source_tier,
        errors=[error],
    )


def ok_run_record(
    agent_name: str, *, started_at: datetime, source_tier: str | None = None, confidence: float | None = None
) -> AgentRunRecord:
    return AgentRunRecord(
        agent_name=agent_name,
        status="ok",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        source_tier=source_tier,
        confidence=confidence,
    )


def degraded_run_record(
    agent_name: str, *, started_at: datetime, reason: str, source_tier: str | None = None
) -> AgentRunRecord:
    return AgentRunRecord(
        agent_name=agent_name,
        status="degraded",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        source_tier=source_tier,
        errors=[reason],
    )


def skipped_run_record(agent_name: str, *, reason: str) -> AgentRunRecord:
    now = datetime.now(timezone.utc)
    return AgentRunRecord(agent_name=agent_name, status="skipped", started_at=now, finished_at=now, errors=[reason])
