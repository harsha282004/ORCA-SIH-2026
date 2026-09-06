"""INCOIS chlorophyll/SST WMS client — Phase 1 Marine Data Foundation.

Structural tests are respx-mocked (no network). One `@pytest.mark.live`
test (excluded from the default run) verifies the real INCOIS WMS.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from app.config import get_settings
from app.data import incois_wms

WMS_URL = incois_wms.INCOIS_WMS_BASE_URL


@respx.mock
def test_fetch_sample_grid_parses_real_shaped_response() -> None:
    respx.get(WMS_URL).mock(return_value=httpx.Response(200, json={"type": "FeatureCollection", "features": [{"properties": {"GRAY_INDEX": 0.2088}}]}))
    samples = incois_wms.fetch_sample_grid(parameter="chl", min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=2)

    assert len(samples) == 4
    assert all(s.value == 0.2088 for s in samples)
    assert all(s.unit == "mg/m^3" for s in samples)


@respx.mock
def test_fetch_sample_grid_handles_missing_value_as_none() -> None:
    respx.get(WMS_URL).mock(return_value=httpx.Response(200, json={"type": "FeatureCollection", "features": []}))
    samples = incois_wms.fetch_sample_grid(parameter="sst", min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=2)

    assert all(s.value is None for s in samples)


@respx.mock
def test_fetch_sample_grid_raises_on_http_failure() -> None:
    respx.get(WMS_URL).mock(return_value=httpx.Response(503, text="service unavailable"))
    with pytest.raises(incois_wms.IncoisWmsError):
        incois_wms.fetch_sample_grid(parameter="chl", min_lat=12.7, min_lon=73.5, max_lat=13.45, max_lon=75.05, samples_per_axis=1)


@pytest.mark.live
def test_live_incois_wms_returns_real_chl_and_sst_values_inside_orca_bbox() -> None:
    bbox = get_settings().demo_bbox
    for parameter, plausible_range in (("chl", (0.0, 30.0)), ("sst", (15.0, 35.0))):
        samples = incois_wms.fetch_sample_grid(
            parameter=parameter, min_lat=bbox.min_lat, min_lon=bbox.min_lon, max_lat=bbox.max_lat, max_lon=bbox.max_lon, samples_per_axis=3
        )
        with_values = [s for s in samples if s.value is not None]
        assert len(with_values) > 0, f"expected at least one real {parameter} value from the live INCOIS WMS"
        for s in with_values:
            assert plausible_range[0] <= s.value <= plausible_range[1]
