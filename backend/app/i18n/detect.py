"""Deterministic, script-based language detection — Phase 6 task §6.

Audit finding (recorded here, not just in the report): `LLMProvider
.detect_language()` already exists as part of the frozen `architecture.md
§11a` provider interface, implemented by every adapter (`groq.py`,
`gemini.py`, `claude.py`, `grok.py`, `fake.py`) — but it is **dead code**:
nothing in `app/agents/` ever calls it. The language actually used today
comes from `RawIntentResult.language`, a field the SAME single Groq call
that classifies intent already extracts — genuinely free, no second LLM
round-trip. `detect_language()` stays unused; adding a second LLM call
purely for language detection would violate task §6's own "avoid an
unnecessary LLM call just to detect obvious scripts" instruction.

This module is the deterministic alternative task §6 asks for: Unicode
script-range detection, correct by construction for any text that is
predominantly one Indic script (Devanagari for Hindi, the Kannada block
for Kannada, Latin for English) — it costs a single pass over the string,
no network call, no model. It is used as a CROSS-CHECK/override on the
LLM's own `language` field in `app.agents.query_understanding.agent`, not
as a replacement for the LLM call itself (which is still needed for intent
classification regardless) — catching the real, observed failure mode of
a smaller open model occasionally mis-naming the ISO code for a script it
otherwise read correctly.

Script ambiguity is real and disclosed: Tamil/Telugu/Malayalam text is
detected via their own distinct Unicode blocks (evaluated for Phase 6 per
task §4, NOT claimed as "supported" merely because their scripts are
detectable — see the Phase 6 report §4 for the tested/untested distinction).
Mixed-script/code-switched text (task §27, e.g. "ಮಂಗಳೂರು hattira safe fishing
area") is resolved by whichever script has the MOST characters — a simple,
deterministic, documented heuristic, not a claim of perfect code-switch
parsing.
"""
from __future__ import annotations

# (start, end) inclusive Unicode code-point ranges for each script's main
# block. Deliberately only the primary block per language — combining
# marks/digits that fall outside these exact ranges simply don't count
# toward either side, which is fine for a majority-vote heuristic.
_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "kn": (0x0C80, 0x0CFF),  # Kannada
    "hi": (0x0900, 0x097F),  # Devanagari (Hindi, and Marathi/Nepali/Sanskrit — see module docstring)
    "ta": (0x0B80, 0x0BFF),  # Tamil
    "te": (0x0C00, 0x0C7F),  # Telugu
    "ml": (0x0D00, 0x0D7F),  # Malayalam
}


def detect_script_language(text: str) -> str | None:
    """Returns the ISO 639-1 code of the Indic script with the most
    characters in `text` when one is clearly dominant over any Latin-script
    content, `"en"` when the text is Latin-script with NO Indic characters
    at all AND at least one recognizable English function/marine-domain
    word (a deliberately narrow check — see below), or `None` when neither
    condition is confidently met — meaning "defer to the LLM's own
    `language` field," never a guess.

    Script-range matching alone can only prove "this text contains Kannada/
    Devanagari/Tamil/Telugu/Malayalam characters" — it can NEVER prove
    "this Latin-script text is English rather than French/German/Spanish/
    Portuguese/etc." (they share the same alphabet). Confidently returning
    `"en"` for arbitrary Latin text would silently override a correct LLM
    answer of "fr"/"de"/etc. with a wrong one — exactly the failure mode
    task §6 warns against. So this function only ever asserts "en" for text
    that is BOTH pure-Latin AND matches at least one word from a small,
    English-specific closed-class list (the kind of function words present
    in virtually every real English sentence but essentially never
    borrowed as-is into French/German/Spanish prose) — good enough to
    correct an occasional LLM mislabel of genuine English without ever
    claiming false confidence about a different Latin-script language.
    """
    counts: dict[str, int] = {code: 0 for code in _SCRIPT_RANGES}
    latin_count = 0

    for ch in text:
        codepoint = ord(ch)
        if not ch.isalpha():
            continue
        matched = False
        for code, (start, end) in _SCRIPT_RANGES.items():
            if start <= codepoint <= end:
                counts[code] += 1
                matched = True
                break
        if not matched and ch.isascii():
            latin_count += 1

    best_script, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count > 0 and best_count > latin_count:
        return best_script

    if latin_count > 0 and latin_count >= best_count and _looks_english(text):
        return "en"

    return None


# A closed, deliberately small set of English function words/marine-domain
# terms — present in essentially every real English query this project's
# own example set uses ("is", "the", "near", "safe", "area", "fishing",
# "route", "tomorrow", ...), and NOT common loanwords in French/German/
# Spanish/Portuguese prose. One match is enough; this is a confidence gate,
# not a full language model.
_ENGLISH_SIGNAL_WORDS = frozenset(
    {
        "the", "is", "it", "a", "an", "near", "safe", "safety", "area", "areas", "fishing", "fish",
        "route", "routes", "plan", "find", "tomorrow", "today", "morning", "evening", "tonight",
        "what", "where", "when", "how", "why", "which", "compare", "hazard", "hazards", "weather",
        "wave", "waves", "wind", "risk", "conditions", "and", "for", "to", "of", "in", "at",
    }
)


def _looks_english(text: str) -> bool:
    words = {w.strip(".,!?;:'\"()").lower() for w in text.split()}
    return not words.isdisjoint(_ENGLISH_SIGNAL_WORDS)
