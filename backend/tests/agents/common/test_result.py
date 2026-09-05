from datetime import datetime, timedelta, timezone

from app.agents.common.result import build_agent_result, build_failed_agent_result, worst_temporal_validity_status
from app.models.contracts import NormalizedObservation, QualityMetadata

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)


def make_observation(parameter="wave_height", value=1.2, *, missing=False, temporal_validity="VALID") -> NormalizedObservation:
    obs = NormalizedObservation(
        source="test",
        source_type="forecast",
        source_tier="live",
        parameter=parameter,
        value=None if missing else value,
        unit="m",
        latitude=12.9,
        longitude=74.8,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=NOW + timedelta(hours=1),
        is_forecast=True,
        retrieved_at=NOW,
        mode="demo",
        is_live=True,
        quality=QualityMetadata(is_missing=missing, missing_reason="test" if missing else None),
    )
    return obs.model_copy(update={"temporal_validity": temporal_validity})


def test_worst_temporal_validity_status_picks_most_severe() -> None:
    assert worst_temporal_validity_status(["VALID", "STALE", "VALID"]) == "STALE"
    assert worst_temporal_validity_status(["VALID", "EXPIRED", "STALE"]) == "EXPIRED"
    assert worst_temporal_validity_status(["MISSING_TIMESTAMP", "VALID"]) == "MISSING_TIMESTAMP"
    assert worst_temporal_validity_status(["VALID", "VALID"]) == "VALID"


def test_worst_temporal_validity_status_empty_is_missing() -> None:
    assert worst_temporal_validity_status([]) == "MISSING_TIMESTAMP"


def test_build_agent_result_full_data_high_confidence() -> None:
    observations = [make_observation("wave_height", 1.2), make_observation("wave_period", 8.0)]
    result = build_agent_result(
        observations=observations, mode="demo", latitude=12.9, longitude=74.8,
        requested_time=NOW, max_staleness=timedelta(minutes=30), expected_parameter_count=2,
    )
    assert result.status == "ok"
    assert result.data == {"wave_height": 1.2, "wave_period": 8.0}
    assert result.confidence == 1.0  # fresh, complete, agreement=1.0
    assert result.temporal_validity_status == "VALID"
    assert len(result.evidence) == 2


def test_build_agent_result_partial_completeness_reduces_confidence() -> None:
    observations = [make_observation("wave_height", 1.2), make_observation("wave_period", missing=True)]
    result = build_agent_result(
        observations=observations, mode="demo", latitude=12.9, longitude=74.8,
        requested_time=NOW, max_staleness=timedelta(minutes=30), expected_parameter_count=2,
    )
    assert result.confidence < 1.0
    assert result.data == {"wave_height": 1.2}  # missing observation excluded from `data`


def test_build_agent_result_stale_status_rolls_up() -> None:
    observations = [make_observation(temporal_validity="STALE")]
    result = build_agent_result(
        observations=observations, mode="demo", latitude=12.9, longitude=74.8,
        requested_time=NOW, max_staleness=timedelta(minutes=30), expected_parameter_count=1,
    )
    assert result.temporal_validity_status == "STALE"


def test_build_agent_result_source_tier_override() -> None:
    observations = [make_observation()]
    result = build_agent_result(
        observations=observations, mode="demo", latitude=12.9, longitude=74.8,
        requested_time=NOW, max_staleness=timedelta(minutes=30), expected_parameter_count=1,
        source_tier_override="synthetic",
    )
    assert result.source_tier == "synthetic"


def test_build_failed_agent_result() -> None:
    result = build_failed_agent_result(mode="live", latitude=12.9, longitude=74.8, requested_time=NOW, errors=["boom"])
    assert result.status == "failed"
    assert result.confidence == 0.0
    assert result.data == {}
    assert result.evidence == []
    assert result.errors == ["boom"]
    assert result.temporal_validity_status == "MISSING_TIMESTAMP"


def test_build_agent_result_spatial_extent_is_geojson_point() -> None:
    result = build_agent_result(
        observations=[make_observation()], mode="demo", latitude=12.9, longitude=74.8,
        requested_time=NOW, max_staleness=timedelta(minutes=30), expected_parameter_count=1,
    )
    assert result.spatial_extent == {"type": "Point", "coordinates": [74.8, 12.9]}
