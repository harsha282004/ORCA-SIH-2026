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

# Phase 6 (task §17/§30): "Use the existing intent plus conversational
# operation/context... intent: route, operation: compare" — language and
# conversational operation stay ORTHOGONAL to `intent_class`, never a new
# `kannada_fishing`/`route_compare`-style intent. `reference_type ==
# "follow_up_explanation"` (Phase 5, unchanged) already covers "why?" —
# deliberately NOT duplicated here as a third `operation` value.
Operation = Literal["evaluate", "compare"]
# Which previously-returned candidate/route/alternative a follow-up refers
# to ("what about the alternative?", "which is safer?" -> compare BOTH,
# but a single-target follow-up like "what about the second option?" names
# just one). `None` (the default) means "no specific selection referenced"
# — the ordinary, non-conversational path.
SelectionReference = Literal["primary", "alternative"]

# Phase 7 (task §16) — ONLY the two Risk Engine inputs
# `app.risk.components.wave_risk`/`wind_risk` actually consume (the same
# two `app.scenario.models.ScenarioPerturbation` has supported since an
# earlier phase). A closed enum, not a free-text field, so the LLM
# structurally cannot propose an unsupported variable ("fish population",
# "chlorophyll") — it can only ever name one of these two, or leave the
# field unset (task §33's "no biological fabrication").
ScenarioVariable = Literal["wave_height", "wind_speed"]


class ReferenceDelta(BaseModel):
    """architecture.md §31a's exact worked example: for a
    `same_query_different_param` follow-up ("what about 20 km farther
    offshore?"), the LLM's job stops at naming the requested change — it
    never computes the resulting coordinate itself. Deterministic code
    (`app.agents.query_understanding.reference`) turns this into an actual
    offset via `app.gis.distance.offset_point_km`.

    Only the one field architecture.md's own example names is supported —
    adding more would mean inventing scope the architecture never
    specified.

    Named `ReferenceDelta`/`reference_delta` rather than
    "relative change"/coordinate-suggestive wording so the field name
    itself can never trip the structural guarantee that
    `RawIntentResult` contains no coordinate-shaped field (see
    `test_raw_intent_schema_has_no_coordinate_or_absolute_timestamp_fields`).
    """

    offshore_distance_km: float | None = None


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
    # Phase 5 (task §28): for route_planning, the ROUTE'S destination place
    # name — e.g. "Plan a route from Mangaluru to Udupi" -> location_name=
    # "Mangaluru", destination_name="Udupi". A free-text name ONLY, subject
    # to the exact same deterministic resolve_location(...) gazetteer
    # lookup as location_name — never a coordinate, never LLM-computed
    # geometry. None for every non-routing intent.
    destination_name: str | None = None
    time_description: str | None  # free text, e.g. "tomorrow morning", "Friday"
    objective: str
    requires_route: bool
    requires_pfz_reference: bool
    persona: Persona
    refers_to_prior: bool
    reference_type: ReferenceType | None
    reference_delta: ReferenceDelta | None = None
    # Phase 6 — conversational operation/selection, orthogonal to
    # intent_class (see the module-level docstring above `Operation`).
    # Both default to None/unset for a fresh, non-conversational query.
    operation: Operation | None = None
    selection_reference: SelectionReference | None = None
    # Phase 7 (task §4/§17/§32) — a WHAT-IF scenario request. `is_scenario`
    # is set whenever the user is clearly asking "what if X changed"
    # regardless of whether a supported variable/value could be extracted;
    # `scenario_variable`/`scenario_target_value` are populated only when
    # BOTH a supported variable AND an explicit numeric value are present —
    # an underspecified scenario ("what if the ocean gets dangerous", "what
    # if fish increase") leaves one or both `None`, which the deterministic
    # handler turns into a clarification request, never a guessed number.
    is_scenario: bool = False
    scenario_variable: ScenarioVariable | None = None
    scenario_target_value: float | None = None
    # Phase 7 (task §8/§9/§10) — "which time is better", "best time
    # tomorrow", "compare morning and afternoon": a request about a WINDOW
    # of real forecast hours, as opposed to the single instant every other
    # query already resolves via `time_description`/`time_window`. Never
    # invents which hours — `time_window` (below/on IntentResult) still
    # carries the deterministically-resolved start/end the temporal engine
    # bounds itself to.
    wants_temporal_window: bool = False


class IntentResult(BaseModel):
    """Verbatim contract from architecture.md §12."""

    language: str
    intent_class: IntentClass
    activity: str | None
    location: dict  # {type, name, resolved_bbox} — always deterministically resolved, never LLM-sourced
    # Phase 5 (task §28) — same shape as `location`, resolved the same
    # deterministic way from `RawIntentResult.destination_name`. `None`
    # unless the query named a second (destination) place — most intents
    # never populate this, only route_planning does.
    destination: dict | None = None
    time_window: dict  # {start, end} resolved to UTC — always deterministically validated
    objective: str
    constraints: dict
    requires_route: bool
    requires_pfz_reference: bool
    persona: Persona
    refers_to_prior: bool
    reference_type: ReferenceType | None
    reference_delta: ReferenceDelta | None = None
    operation: Operation | None = None
    selection_reference: SelectionReference | None = None
    is_scenario: bool = False
    scenario_variable: ScenarioVariable | None = None
    scenario_target_value: float | None = None
    wants_temporal_window: bool = False


class ClarificationNeeded(BaseModel):
    """architecture.md §38: "Malformed user query -> Query Understanding
    returns a clarification request, not a guessed intent." Also used for
    ambiguous location/time and unsupported-language cases (Phase 5 task
    spec §10, §25).
    """

    reason: str
    missing_fields: list[str]
    original_query: str
