"""NormalizedObservation / Evidence contract tests — Phase 1 §6."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.contracts import NormalizedObservation, QualityMetadata

NOW = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)


def _base_kwargs(**overrides) -> dict:
    kwargs = dict(
        source="open-meteo-marine",
        source_type="forecast",
        source_tier="live",
        parameter="wave_height",
        value=1.4,
        unit="m",
        latitude=12.91,
        longitude=74.79,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=NOW,
        is_forecast=True,
        retrieved_at=NOW,
        mode="live",
        is_live=True,
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_observation_constructs() -> None:
    obs = NormalizedObservation(**_base_kwargs())
    assert obs.crs == "EPSG:4326"
    assert obs.temporal_validity == "MISSING_TIMESTAMP"  # default until the Fabric evaluates it


def test_missing_value_requires_quality_flag() -> None:
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(value=None))  # quality.is_missing still False by default


def test_missing_value_with_quality_flag_is_allowed() -> None:
    obs = NormalizedObservation(
        **_base_kwargs(value=None, quality=QualityMetadata(is_missing=True, missing_reason="not in response"))
    )
    assert obs.value is None
    assert obs.quality.is_missing is True


def test_present_value_cannot_be_flagged_missing() -> None:
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(quality=QualityMetadata(is_missing=True)))


@pytest.mark.parametrize("latitude", [-91.0, 91.0, 200.0])
def test_invalid_latitude_rejected(latitude: float) -> None:
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(latitude=latitude))


@pytest.mark.parametrize("longitude", [-181.0, 181.0, 500.0])
def test_invalid_longitude_rejected(longitude: float) -> None:
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(longitude=longitude))


def test_is_live_must_match_source_tier() -> None:
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(source_tier="synthetic", is_live=True))
    with pytest.raises(ValidationError):
        NormalizedObservation(**_base_kwargs(source_tier="live", is_live=False))


def test_demo_data_cannot_claim_live_tier_and_is_live() -> None:
    # architecture.md §16a: demo/synthetic data must never silently present as live.
    obs = NormalizedObservation(**_base_kwargs(source_tier="synthetic", is_live=False, mode="demo"))
    assert obs.is_live is False


def test_to_evidence_conversion() -> None:
    obs = NormalizedObservation(**_base_kwargs())
    evidence = obs.to_evidence(confidence=0.8)
    assert evidence.source == obs.source
    assert evidence.value == obs.value
    assert evidence.spatial_extent == {"type": "Point", "coordinates": [obs.longitude, obs.latitude]}
    assert evidence.confidence == 0.8


def test_to_evidence_rejects_missing_value() -> None:
    obs = NormalizedObservation(
        **_base_kwargs(value=None, quality=QualityMetadata(is_missing=True, missing_reason="x"))
    )
    with pytest.raises(ValueError):
        obs.to_evidence(confidence=0.5)
