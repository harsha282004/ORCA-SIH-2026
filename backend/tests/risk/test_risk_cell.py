from datetime import datetime, timezone

import pytest

from app.gis.grid import generate_grid
from app.models.geo import BBox
from app.risk.config import get_risk_config
from app.risk.engine import NormalizedRiskComponents, compute_risk
from app.risk.risk_cell import evaluate_cell

BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.1, max_lon=74.1)


def test_evaluate_cell_produces_structured_result() -> None:
    cfg = get_risk_config()
    cell = generate_grid(BBOX, resolution_km=5.0)[0]

    components = NormalizedRiskComponents(
        wave=0.2, wind=0.1, advisory_or_hazard_flag=0.0, lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0, coast_distance=0.1, data_confidence_penalty=0.0,
    )
    risk_result = compute_risk(components, cfg.risk_weights, cfg.risk_thresholds)

    cell_result = evaluate_cell(
        cell,
        risk_result,
        confidence=0.9,
        valid_time=datetime(2026, 9, 5, tzinfo=timezone.utc),
        data_quality="fixture",
        constraints=[],
    )

    assert cell_result.cell_id == cell.cell_id
    assert cell_result.risk_score == risk_result.score
    assert cell_result.risk_level == risk_result.level
    assert cell_result.confidence == 0.9
    assert cell_result.data_quality == "fixture"
    assert cell_result.geometry_geojson["type"] == "Polygon"


def test_evaluate_cell_rejects_invalid_confidence() -> None:
    cfg = get_risk_config()
    cell = generate_grid(BBOX, resolution_km=5.0)[0]
    components = NormalizedRiskComponents(
        wave=0.0, wind=0.0, advisory_or_hazard_flag=0.0, lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0, coast_distance=0.0, data_confidence_penalty=0.0,
    )
    risk_result = compute_risk(components, cfg.risk_weights, cfg.risk_thresholds)

    with pytest.raises(ValueError):
        evaluate_cell(
            cell, risk_result, confidence=1.5, valid_time=datetime.now(timezone.utc), data_quality="fixture"
        )


def test_evaluate_cell_carries_constraints() -> None:
    cfg = get_risk_config()
    cell = generate_grid(BBOX, resolution_km=5.0)[0]
    components = NormalizedRiskComponents(
        wave=0.0, wind=0.0, advisory_or_hazard_flag=0.0, lightning_thunderstorm_proxy=0.0,
        restricted_zone_distance=0.0, coast_distance=0.0, data_confidence_penalty=0.0,
    )
    risk_result = compute_risk(components, cfg.risk_weights, cfg.risk_thresholds)

    cell_result = evaluate_cell(
        cell,
        risk_result,
        confidence=0.5,
        valid_time=datetime.now(timezone.utc),
        data_quality="fixture",
        constraints=["hard_geofence_land"],
    )
    assert cell_result.constraints == ["hard_geofence_land"]
