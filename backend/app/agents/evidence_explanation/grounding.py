"""Post-generation grounding + safety-claim checks — architecture.md §12's
hallucination-reduction mechanism #5: "A post-generation grounding check
verifies every numeric token in generated explanation text matches a value
present in its input evidence object; failing outputs are rejected and
regenerated once, then fall back to a templated explanation."

Phase 5 task spec §20 adds a second, equally critical check this module
also implements: the explanation may never contradict a `NO_SAFE_RECOMMENDATION`
decision by claiming safety in prose — a decision outcome check, not just
a numeric one.
"""
from __future__ import annotations

import re

_NUMERIC_TOKEN_RE = re.compile(r"-?\d+\.?\d*")

# A deliberately narrow, documented blocklist — this is a heuristic
# safety net on top of the deterministic decision/safety outcomes (which
# remain authoritative regardless), not a claim of perfect NLP
# safety-claim detection.
_UNSAFE_AFFIRMATION_PHRASES = (
    "is safe",
    "safe to",
    "go ahead",
    "you can fish",
    "it is recommended",
    "we recommend",
    "safe conditions",
    "proceed with",
)


def extract_numeric_tokens(text: str) -> list[float]:
    tokens: list[float] = []
    for match in _NUMERIC_TOKEN_RE.findall(text):
        try:
            tokens.append(float(match))
        except ValueError:
            continue
    return tokens


def check_grounding(text: str, evidence_values: list[float], *, tolerance: float = 0.05) -> bool:
    """Every numeric token in `text` must be within `tolerance` of some
    value actually present in `evidence_values` — rounding/formatting
    differences ("1.4" vs "1.40") are tolerated; a number that doesn't
    trace to any evidence value is not.
    """
    tokens = extract_numeric_tokens(text)
    if not tokens:
        return True
    return all(any(abs(token - value) <= tolerance for value in evidence_values) for token in tokens)


def check_no_false_safety_claim(text: str, *, decision_outcome: str | None) -> bool:
    """architecture.md Phase 5 task spec §20: if the Decision Engine says
    NO_SAFE_RECOMMENDATION, the explanation must never say "it is safe" —
    checked here as a real string scan, not just documented as a rule.
    """
    if decision_outcome != "NO_SAFE_RECOMMENDATION":
        return True
    lowered = text.lower()
    return not any(phrase in lowered for phrase in _UNSAFE_AFFIRMATION_PHRASES)


def is_grounded_and_safe(text: str, evidence_values: list[float], *, decision_outcome: str | None) -> bool:
    return check_grounding(text, evidence_values) and check_no_false_safety_claim(text, decision_outcome=decision_outcome)
