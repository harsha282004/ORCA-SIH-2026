"""Query Understanding data contracts — architecture.md §12 (`IntentResult`,
verbatim) and §10/§30/§31a's location/time-resolution discipline.

Two schemas, deliberately different, mirroring §31a's own principle ("LLM
interprets *what the user means*; it must never compute the geometry that
reference implies") applied one step earlier, to the very first location
resolution:

- `RawIntentResult` — what the LLM is actually asked to produce. Notably,
  it has NO coordinate/bbox field at all — only a free-text
  `location_name`. This makes it structurally impossible for the LLM to
  inject a hallucinated coordinate into the pipeline, rather than relying
  on a downstream check to catch it.
- `IntentResult` — the architecture §12 contract, with `location` and
  `time_window` populated entirely by deterministic post-processing
  (`app.agents.query_understanding.agent`), never copied from the LLM.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

IntentClass = Literal["safety_check", "zone_recommendation", "route_planning", "diagnostic_exploration", "boundary_check"]
Persona = Literal["fisherman", "researcher", "authority", "operator"]
ReferenceType = Literal["same_query_different_param", "follow_up_explanation", "new_query"]


class RawIntentResult(BaseModel):
    """The LLM-facing schema — architecture.md §12's IntentResult fields,
    minus anything that would let the model emit geometry or absolute
    timestamps directly. `time_start_description`/`time_end_description`
    are free-text natural-language time references (e.g. "tomorrow
    morning"); resolving them to actual UTC timestamps is deterministic
    post-processing, not trusted LLM arithmetic.
    """

    language: str  # ISO 639-1
    intent_class: IntentClass
    activity: str | None
    location_name: str | None  # a place name string ONLY — never coordinates
    time_description: str | None  # free text, e.g. "tomorrow morning", "Friday"
    objective: str
    requires_route: bool
    requires_pfz_reference: bool
    persona: Persona
    refers_to_prior: bool
    reference_type: ReferenceType | None


class IntentResult(BaseModel):
    """Verbatim contract from architecture.md §12."""

    language: str
    intent_class: IntentClass
    activity: str | None
    location: dict  # {type, name, resolved_bbox} — always deterministically resolved, never LLM-sourced
    time_window: dict  # {start, end} resolved to UTC — always deterministically validated
    objective: str
    constraints: dict
    requires_route: bool
    requires_pfz_reference: bool
    persona: Persona
    refers_to_prior: bool
    reference_type: ReferenceType | None


class ClarificationNeeded(BaseModel):
    """architecture.md §38: "Malformed user query -> Query Understanding
    returns a clarification request, not a guessed intent." Also used for
    ambiguous location/time and unsupported-language cases (Phase 5 task
    spec §10, §25).
    """

    reason: str
    missing_fields: list[str]
    original_query: str
