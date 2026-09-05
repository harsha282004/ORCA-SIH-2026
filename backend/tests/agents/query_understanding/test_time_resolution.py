from datetime import datetime, timezone

from app.agents.query_understanding.time_resolution import resolve_time_window

NOW = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)  # a Saturday


def test_empty_description_resolves_to_today() -> None:
    window = resolve_time_window(None, now=NOW)
    assert window["start"].startswith("2026-09-05")


def test_tomorrow_resolves_to_next_day() -> None:
    window = resolve_time_window("tomorrow", now=NOW)
    assert window["start"].startswith("2026-09-06")


def test_tomorrow_morning_resolves_to_morning_hour_range() -> None:
    window = resolve_time_window("tomorrow morning", now=NOW)
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    assert start.hour == 6
    assert end.hour == 11


def test_weekday_name_resolves_to_the_next_occurrence() -> None:
    # NOW is Saturday 2026-09-05; "Monday" should resolve to 2026-09-07.
    window = resolve_time_window("Monday", now=NOW)
    assert window["start"].startswith("2026-09-07")


def test_naming_todays_own_weekday_means_next_week() -> None:
    # NOW is a Saturday; "Saturday" should resolve to 2026-09-12, not today.
    window = resolve_time_window("Saturday", now=NOW)
    assert window["start"].startswith("2026-09-12")


def test_an_already_past_window_falls_back_to_next_24h() -> None:
    late_night = datetime(2026, 9, 5, 23, 30, 0, tzinfo=timezone.utc)
    window = resolve_time_window("this morning", now=late_night)
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    assert start == late_night
    assert (end - start).total_seconds() == 24 * 3600


def test_deterministic_given_same_inputs() -> None:
    assert resolve_time_window("tomorrow afternoon", now=NOW) == resolve_time_window("tomorrow afternoon", now=NOW)
