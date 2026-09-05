"""DEMO_BBOX and configuration validation — Phase 1."""
import pytest

from app.config import Settings


def test_default_demo_bbox_is_valid() -> None:
    settings = Settings()
    bbox = settings.demo_bbox
    assert bbox.min_lat < bbox.max_lat
    assert bbox.min_lon < bbox.max_lon


def test_default_demo_bbox_covers_mangaluru_and_udupi() -> None:
    # Mangaluru (~12.87N, 74.88E) and Udupi (~13.34N, 74.75E) must both fall
    # inside the configured demo bbox — architecture.md §44 fixes the region
    # by name; this test pins the *proposed* numeric box to that name.
    settings = Settings()
    bbox = settings.demo_bbox
    assert bbox.contains(12.87, 74.88), "Mangaluru must be inside DEMO_BBOX"
    assert bbox.contains(13.34, 74.75), "Udupi must be inside DEMO_BBOX"


def test_invalid_demo_bbox_is_rejected() -> None:
    settings = Settings(
        demo_bbox_min_lat=13.0,
        demo_bbox_max_lat=12.0,  # min > max — invalid
        demo_bbox_min_lon=73.5,
        demo_bbox_max_lon=75.0,
    )
    with pytest.raises(ValueError):
        _ = settings.demo_bbox


def test_open_meteo_urls_configured() -> None:
    settings = Settings()
    assert settings.open_meteo_weather_base_url.startswith("https://api.open-meteo.com")
    assert settings.open_meteo_marine_base_url.startswith("https://marine-api.open-meteo.com")


def test_http_timeout_is_bounded() -> None:
    settings = Settings()
    assert 0 < settings.http_timeout_seconds <= 30
