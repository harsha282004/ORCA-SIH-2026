"""GEBCO bathymetry client — Phase 1 Marine Data Foundation.

Structural tests are respx-mocked (no network). One `@pytest.mark.live`
test (excluded from the default run, matching tests/test_live_open_meteo.py's
convention) verifies the real GEBCO WMS end-to-end.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from app.config import get_settings
from app.data import gebco

WMS_URL = gebco.GEBCO_WMS_BASE_URL


@respx.mock
def test_fetch_depth_grid_parses_real_shaped_response() -> None:
    respx.get(WMS_URL).mock(
        return_value=httpx.Response(
            200,
            text="GetFeatureInfo results:\n\nLayer 'GEBCO_LATEST_2'\n  Feature 0: \n    x = '74.277083'\n    y = '13.072917'\n    value_list = '-56'\n",
        )
    )
    samples = gebco.fetch_depth_grid(min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=2)

    assert len(samples) == 4
    assert all(s.depth_m == -56.0 for s in samples)
    assert all(s.tid == -56.0 for s in samples)  # same mocked response for both layers in this structural test


@respx.mock
def test_fetch_depth_grid_handles_no_results_as_none_not_zero() -> None:
    respx.get(WMS_URL).mock(return_value=httpx.Response(200, text="GetFeatureInfo results:\n\n  Search returned no results.\n"))
    samples = gebco.fetch_depth_grid(min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=2)

    assert len(samples) == 4
    assert all(s.depth_m is None for s in samples)  # never fabricated as 0.0


@respx.mock
def test_fetch_depth_grid_raises_gebco_error_on_http_failure() -> None:
    respx.get(WMS_URL).mock(return_value=httpx.Response(500, text="internal error"))
    with pytest.raises(gebco.GebcoError):
        gebco.fetch_depth_grid(min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=1)


def test_fetch_depth_grid_rejects_invalid_samples_per_axis() -> None:
    with pytest.raises(ValueError):
        gebco.fetch_depth_grid(min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=0)


@pytest.mark.live
def test_live_gebco_wms_returns_a_real_depth_value_inside_orca_bbox() -> None:
    bbox = get_settings().demo_bbox
    lat, lon = bbox.center()
    samples = gebco.fetch_depth_grid(min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon, samples_per_axis=3)

    assert len(samples) == 9
    with_values = [s for s in samples if s.depth_m is not None]
    assert len(with_values) > 0
    for s in with_values:
        assert bbox.min_lat <= s.latitude <= bbox.max_lat
        assert bbox.min_lon <= s.longitude <= bbox.max_lon
        assert -12000 <= s.depth_m <= 9000  # plausible Earth elevation/depth range, not a fabricated sanity bound
