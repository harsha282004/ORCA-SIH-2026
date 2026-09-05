"""Multi-turn session state — architecture.md §31.

Deliberately narrow: this remembers *conversational* context only (the
prior turn's understood intent, the decision that was made, and its
provenance/language) so a follow-up like "what about tomorrow?" can be
resolved relative to something. It never caches environmental
observations as still-current — every new turn re-runs the Weather/
Oceanographic agents (and therefore the Temporal Validity Gate) fresh,
regardless of what is stored here (Phase 5 task spec §24/§31).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.agents.query_understanding.models import IntentResult
from app.decision.models import Decision
from app.i18n.languages import DEFAULT_LANGUAGE
from app.provenance.models import DecisionProvenanceGraph


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    turn_count: int = 0

    last_query: str | None = None
    last_language: str = DEFAULT_LANGUAGE
    last_intent: IntentResult | None = None
    last_decision: Decision | None = None
    last_provenance: DecisionProvenanceGraph | None = None
