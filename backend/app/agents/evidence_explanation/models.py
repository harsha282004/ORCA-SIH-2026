"""Evidence & Explanation Agent data contracts — architecture.md §28."""
from __future__ import annotations

from pydantic import BaseModel

from app.provenance.models import DecisionProvenanceGraph


class ExplanationOutput(BaseModel):
    """The LLM-facing schema — the model's ENTIRE output is this one
    grounded rationale string. It cannot emit a decision, a risk score, or
    any other field — there is nothing else in the schema for it to fill.
    """

    rationale: str


class ExplanationResult(BaseModel):
    rationale: str
    language: str
    grounded: bool
    used_fallback_template: bool
    provenance: DecisionProvenanceGraph
