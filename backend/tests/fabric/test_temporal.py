from datetime import datetime, timedelta, timezone

from app.fabric.temporal import evaluate_temporal_validity, freshness_seconds, to_utc

T0 = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)
MAX_STALENESS = timedelta(minutes=30)


def test_valid_when_fresh_and_in_window() -> None:
    status = evaluate_temporal_validity(
        observed_at=T0,
        valid_from=T0,
        valid_to=T0 + timedelta(hours=1),
        retrieved_at=T0,
        requested_time=T0 + timedelta(minutes=5),
        max_staleness=MAX_STALENESS,
    )
    assert status == "VALID"


def test_stale_when_retrieved_too_long_ago() -> None:
    status = evaluate_temporal_validity(
        observed_at=T0,
        valid_from=T0,
        valid_to=T0 + timedelta(hours=6),
        retrieved_at=T0,
        requested_time=T0 + timedelta(hours=2),  # 2h since retrieval > 30min max staleness
        max_staleness=MAX_STALENESS,
    )
    assert status == "STALE"


def test_expired_when_outside_validity_window() -> None:
    status = evaluate_temporal_validity(
        observed_at=T0,
        valid_from=T0,
        valid_to=T0 + timedelta(hours=1),
        retrieved_at=T0,
        requested_time=T0 + timedelta(hours=5),
        max_staleness=MAX_STALENESS,
    )
    assert status == "EXPIRED"


def test_missing_timestamp_when_observed_at_is_none() -> None:
    status = evaluate_temporal_validity(
        observed_at=None,
        valid_from=None,
        valid_to=None,
        retrieved_at=T0,
        requested_time=T0,
        max_staleness=MAX_STALENESS,
    )
    assert status == "MISSING_TIMESTAMP"


def test_invalid_timestamp_when_naive_datetime() -> None:
    naive = datetime(2026, 9, 5, 3, 0)  # no tzinfo
    status = evaluate_temporal_validity(
        observed_at=naive,
        valid_from=naive,
        valid_to=naive + timedelta(hours=1),
        retrieved_at=T0,
        requested_time=T0,
        max_staleness=MAX_STALENESS,
    )
    assert status == "INVALID_TIMESTAMP"


def test_invalid_timestamp_when_valid_from_after_valid_to() -> None:
    status = evaluate_temporal_validity(
        observed_at=T0,
        valid_from=T0 + timedelta(hours=2),
        valid_to=T0,
        retrieved_at=T0,
        requested_time=T0,
        max_staleness=MAX_STALENESS,
    )
    assert status == "INVALID_TIMESTAMP"


def test_freshness_seconds() -> None:
    assert freshness_seconds(T0, T0 + timedelta(seconds=90)) == 90.0


def test_to_utc_adds_timezone_to_naive() -> None:
    naive = datetime(2026, 9, 5, 3, 0)
    converted = to_utc(naive)
    assert converted.tzinfo is not None
