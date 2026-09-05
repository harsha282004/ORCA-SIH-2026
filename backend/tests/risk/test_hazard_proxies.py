import pytest

from app.risk.config import CycloneProxyWeights
from app.risk.hazard_proxies import CycloneProxyInputs, cyclone_proxy, lightning_thunderstorm_proxy

EQUAL_WEIGHTS = CycloneProxyWeights(
    pressure_tendency=0.2, sustained_wind=0.2, wind_gust=0.2, spatial_persistence=0.2, temporal_persistence=0.2
)


@pytest.mark.parametrize("code", [95, 96, 97, 98, 99])
def test_lightning_proxy_triggers_on_thunderstorm_codes(code: int) -> None:
    assert lightning_thunderstorm_proxy(code) == 1.0


@pytest.mark.parametrize("code", [0, 1, 45, 61, 80, 94, 100])
def test_lightning_proxy_does_not_trigger_outside_range(code: int) -> None:
    assert lightning_thunderstorm_proxy(code) == 0.0


def test_cyclone_proxy_all_zero() -> None:
    inputs = CycloneProxyInputs(
        pressure_tendency=0.0, sustained_wind=0.0, wind_gust=0.0, spatial_persistence=0.0, temporal_persistence=0.0
    )
    assert cyclone_proxy(inputs, EQUAL_WEIGHTS) == 0.0


def test_cyclone_proxy_all_max() -> None:
    inputs = CycloneProxyInputs(
        pressure_tendency=1.0, sustained_wind=1.0, wind_gust=1.0, spatial_persistence=1.0, temporal_persistence=1.0
    )
    assert cyclone_proxy(inputs, EQUAL_WEIGHTS) == pytest.approx(1.0)


def test_cyclone_proxy_weighted_combination() -> None:
    inputs = CycloneProxyInputs(
        pressure_tendency=1.0, sustained_wind=0.0, wind_gust=0.0, spatial_persistence=0.0, temporal_persistence=0.0
    )
    assert cyclone_proxy(inputs, EQUAL_WEIGHTS) == pytest.approx(0.2)


def test_cyclone_proxy_inputs_reject_out_of_range() -> None:
    with pytest.raises(Exception):
        CycloneProxyInputs(
            pressure_tendency=1.5, sustained_wind=0.0, wind_gust=0.0, spatial_persistence=0.0, temporal_persistence=0.0
        )


def test_cyclone_proxy_is_deterministic() -> None:
    inputs = CycloneProxyInputs(
        pressure_tendency=0.4, sustained_wind=0.3, wind_gust=0.6, spatial_persistence=0.2, temporal_persistence=0.9
    )
    results = {cyclone_proxy(inputs, EQUAL_WEIGHTS) for _ in range(5)}
    assert len(results) == 1
