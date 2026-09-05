"""Deterministic time-window resolution — architecture.md §12's
`IntentResult.time_window`, resolved to UTC.

**Not a general natural-language date parser.** Covers the phrasings
expected in ORCA's demo queries ("today", "tomorrow", "tomorrow morning/
afternoon/evening/night", weekday names) with a documented, conservative
fallback (next 24h from `now`) for anything else or anything that would
otherwise resolve to an already-past window. This is a deliberate, bounded
scope decision — not a claim of full NLP date understanding — the LLM
itself is never trusted to compute an absolute timestamp directly (Phase 5
task spec §11's coordinate-safety principle, applied the same way here).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_PART_OF_DAY_HOURS: dict[str, tuple[int, int]] = {
    "morning": (6, 11),
    "afternoon": (12, 16),
    "evening": (17, 20),
    "tonight": (20, 23),
    "night": (20, 23),
}


def resolve_time_window(time_description: str | None, *, now: datetime | None = None) -> dict:
    """Returns `{"start": iso, "end": iso}` in UTC. Deterministic given the
    same `(time_description, now)`.
    """
    now = now or datetime.now(timezone.utc)
    text = (time_description or "").strip().lower()

    base_day = now
    if "tomorrow" in text:
        base_day = now + timedelta(days=1)
    elif not text or "today" in text or "now" in text:
        base_day = now
    else:
        for i, weekday_name in enumerate(_WEEKDAYS):
            if weekday_name in text:
                days_ahead = (i - now.weekday()) % 7
                days_ahead = days_ahead or 7  # naming today's own weekday means NEXT week's occurrence
                base_day = now + timedelta(days=days_ahead)
                break

    start_hour, end_hour = 0, 23
    for part, (start_h, end_h) in _PART_OF_DAY_HOURS.items():
        if part in text:
            start_hour, end_hour = start_h, end_h
            break

    day_start = base_day.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_start + timedelta(hours=start_hour)
    end = day_start + timedelta(hours=end_hour, minutes=59, seconds=59)

    if end < now:
        # The resolved window has already fully passed (e.g. "today
        # morning" asked late at night) — default to a safe forward-
        # looking window rather than returning one the Temporal Validity
        # Gate would reject for a confusing reason.
        start, end = now, now + timedelta(hours=24)

    return {"start": start.isoformat(), "end": end.isoformat()}
