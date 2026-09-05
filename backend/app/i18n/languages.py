"""Language support — architecture.md §30: "MVP scope: text-in/text-out for
2-3 demo languages — recommend English + Hindi + Kannada."

Deliberately minimal, per Phase 5 task spec §26: "Do not put safety-critical
decisions into translated natural-language strings... machine-readable
outcomes remain language-neutral... only presentation/explanation is
localized." This module is therefore just the supported-language set and a
label table for the handful of machine-readable enums a UI might want a
human-readable label for — it is NOT a full i18n/translation framework, and
it never touches `RiskLevel`, `SafetyGuardOutcome`, or `DecisionOutcome`
themselves, which stay as their exact English enum values everywhere in the
graph state, the API response, and any persistence.
"""
from __future__ import annotations

SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "hi", "kn"})

DEFAULT_LANGUAGE = "en"

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
}


def is_supported(language: str) -> bool:
    return language in SUPPORTED_LANGUAGES


def language_display_name(language: str) -> str:
    return _LANGUAGE_NAMES.get(language, language)
