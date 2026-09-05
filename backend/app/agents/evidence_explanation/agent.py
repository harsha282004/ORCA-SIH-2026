"""Evidence & Explanation Agent — architecture.md §10, §12, §28.

"The Evidence & Explanation Agent's *only* job is to turn the Decision
Provenance Graph + Decision Engine output into readable prose, in the
detected language, at the detected persona's level of detail. It cannot
add facts not present in its input." (§28)

The LLM here has no tools, no internet access, and no ability to call any
deterministic engine — it only ever sees a fixed, structured summary of
`DecisionProvenanceGraph` and must produce prose. Two independent
post-generation checks (grounding.py) gate every LLM output before it is
trusted:

1. Every numeric token must trace to a value actually in the provenance.
2. If the decision is NO_SAFE_RECOMMENDATION, the text must not claim safety.

A failing output is regenerated once (with a corrective instruction
appended), then falls back to a fully deterministic template
(architecture.md §12's own documented fallback behavior).
"""
from __future__ import annotations

import json

from app.agents.evidence_explanation.grounding import is_grounded_and_safe
from app.agents.evidence_explanation.models import ExplanationOutput, ExplanationResult
from app.agents.evidence_explanation.template import build_templated_explanation
from app.config import Settings, get_settings
from app.llm.base import LLMProvider, LLMProviderError
from app.llm.factory import get_llm_provider
from app.provenance.models import DecisionProvenanceGraph

_MAX_ATTEMPTS = 2


class EvidenceExplanationAgent:
    def __init__(self, *, llm_provider: LLMProvider | None = None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._llm_provider = llm_provider or get_llm_provider(self._settings)

    def explain(self, *, provenance: DecisionProvenanceGraph, language: str, persona: str) -> ExplanationResult:
        evidence_values = _collect_numeric_values(provenance)
        decision_outcome = provenance.decision.outcome if provenance.decision else None
        system_prompt = _build_system_prompt(provenance, language=language, persona=persona)

        for attempt in range(_MAX_ATTEMPTS):
            try:
                output = self._llm_provider.generate_structured(
                    schema=ExplanationOutput, system_prompt=system_prompt, user_prompt="Produce the explanation now."
                )
            except LLMProviderError:
                break  # fall through to the deterministic template

            if is_grounded_and_safe(output.rationale, evidence_values, decision_outcome=decision_outcome):
                return ExplanationResult(
                    rationale=output.rationale, language=language, grounded=True, used_fallback_template=False,
                    provenance=provenance,
                )

            if attempt == 0:
                system_prompt += (
                    "\n\nYour previous attempt used a number or safety claim not present in the evidence above. "
                    "Use ONLY the numbers given, and do not claim the situation is safe if the decision is "
                    "NO_SAFE_RECOMMENDATION."
                )

        template = build_templated_explanation(provenance)
        return ExplanationResult(
            rationale=template, language="en", grounded=True, used_fallback_template=True, provenance=provenance
        )


def _collect_numeric_values(provenance: DecisionProvenanceGraph) -> list[float]:
    values: list[float] = []
    if provenance.risk is not None:
        values.append(provenance.risk.score)
        for factor in provenance.risk.factors:
            values.extend([factor.normalized_value, factor.weight, factor.contribution])
    if provenance.suitability is not None:
        values.append(provenance.suitability.signal_score)
        values.append(provenance.suitability.suitability_score)
    if provenance.route is not None:
        values.append(provenance.route.distance_km)
        values.append(provenance.route.total_cost)
    if provenance.decision is not None:
        values.append(provenance.decision.risk_score)
        values.append(provenance.decision.confidence)
    return values


def _build_system_prompt(provenance: DecisionProvenanceGraph, *, language: str, persona: str) -> str:
    facts = {
        "decision": provenance.decision.model_dump(mode="json") if provenance.decision else None,
        "risk": provenance.risk.model_dump(mode="json") if provenance.risk else None,
        "suitability": provenance.suitability.model_dump(mode="json") if provenance.suitability else None,
        "safety": provenance.safety.model_dump(mode="json") if provenance.safety else None,
        "route": provenance.route.model_dump(mode="json") if provenance.route else None,
        "conflicts": [c.model_dump(mode="json") for c in provenance.conflicts],
    }
    return f"""You are ORCA's Evidence & Explanation component for a marine-safety assistant.

You must produce a short, clear explanation grounded ONLY in the structured facts below.
Do not invent any fact, number, or source not present here. Do not independently assess
risk or safety — those are already decided. Respond in language code "{language}", at a
level of detail appropriate for a "{persona}".

CRITICAL: if decision.outcome is "NO_SAFE_RECOMMENDATION", you must NOT say the situation
is safe, recommend the activity, or imply it is acceptable to proceed.

Structured facts (JSON):
{json.dumps(facts, indent=2)}
"""
