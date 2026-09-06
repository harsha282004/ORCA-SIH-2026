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
#
# Phase 6 finding (task §8/§38): this list was English-only through
# Phase 5. Since `EvidenceExplanationAgent.explain()` is asked to respond
# in the detected/requested language (`app.i18n.languages
# .SUPPORTED_LANGUAGES` = en/hi/kn), a Kannada or Hindi explanation for a
# NO_SAFE_RECOMMENDATION decision could contain a false "it is safe"
# affirmation that this check would never catch — a real, language-
# specific gap, not a hypothetical one. Extended with the direct Hindi/
# Kannada equivalents of the same handful of phrases — the SAME heuristic
# safety-net role, still never a claim of complete multilingual NLP
# coverage, and still never the actual safety authority (the deterministic
# Decision Engine's NO_SAFE_RECOMMENDATION outcome is authoritative
# regardless of whether this text check catches every possible phrasing).
_UNSAFE_AFFIRMATION_PHRASES = (
    # English
    "is safe",
    "safe to",
    "go ahead",
    "you can fish",
    "it is recommended",
    "we recommend",
    "safe conditions",
    "proceed with",
    # Hindi (Devanagari) — "is safe", "you can go", "proceed" — kept as
    # multi-word phrases (not the bare stems "सुरक्षित"/"अनुशंसित" alone),
    # the same way the English list uses "is safe"/"safe to" rather than
    # the bare word "safe" — a bare stem would also match its own negation
    # ("सुरक्षित नहीं" = "NOT safe"), which must never be flagged.
    "सुरक्षित है",
    "सुरक्षित हैं",
    "जा सकते हैं",
    "आगे बढ़ें",
    # Kannada — "is safe", "you can fish/proceed" — same multi-word
    # discipline as above (never the bare stem "ಸುರಕ್ಷಿತ", which also
    # matches its own negation "ಸುರಕ್ಷಿತವಲ್ಲ" = "NOT safe").
    "ಸುರಕ್ಷಿತವಾಗಿದೆ",
    "ಮೀನುಗಾರಿಕೆ ಮಾಡಬಹುದು",
    "ಮುಂದುವರಿಸಬಹುದು",
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
