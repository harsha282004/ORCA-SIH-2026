"""Deterministic templated explanation — architecture.md §12's fallback
when the LLM is unavailable or fails grounding twice. English only (no
deterministic translation exists without the LLM itself — an honest,
documented limitation, not a silent quality drop presented as equivalent).
Every number here is read directly from `provenance`, never invented.
"""
from __future__ import annotations

from app.provenance.models import DecisionProvenanceGraph


def build_templated_explanation(provenance: DecisionProvenanceGraph) -> str:
    if provenance.decision is None:
        return "ORCA could not complete a decision for this query due to insufficient information."

    decision = provenance.decision
    lines = [f"ORCA's determination: {decision.outcome}."]

    if provenance.risk is not None:
        lines.append(f"Risk level: {provenance.risk.level} (score {provenance.risk.score:.2f}).")

    if provenance.safety is not None and provenance.safety.outcome != "PASS":
        lines.append(f"Safety check result: {provenance.safety.outcome} — {provenance.safety.reason}")

    if decision.outcome == "NO_SAFE_RECOMMENDATION":
        lines.append("ORCA is not able to provide a safe recommendation for this query at this time.")
    elif decision.outcome == "PROVIDE_ALTERNATIVES":
        lines.append("The requested area carries elevated risk; ORCA suggests considering an alternative location.")

    lines.append(decision.reason)
    lines.append(
        "This is ORCA's own configured engineering assessment, not an official government advisory, "
        "and does not guarantee safety."
    )
    return " ".join(lines)
