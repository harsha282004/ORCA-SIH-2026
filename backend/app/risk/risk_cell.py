"""Deterministic spatial risk representation — architecture.md §18's candidate
grid + §33's `risk_cells` concept, restricted to what Phase 2 actually
needs (grid geometry + a risk/confidence result attached to it).

This is NOT the final `risk_cells` database table from architecture.md §33
(that is tied to a `recommendation_id` that doesn't exist until the
Decision Engine + a real query pipeline exist, Phase 4+) — it is the
in-memory representation later phases will populate from real fused
evidence. Phase 2 only ever populates it from test fixtures (see
backend/tests/test_phase2_e2e.py); it must never be populated with
invented "real" environmental values.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.gis.grid import GridCell
from app.risk.engine import RiskResult

DataQuality = Literal["fixture", "live"]


class RiskCellResult(BaseModel):
    cell_id: str
    geometry_geojson: dict
    risk_score: float
    risk_level: str
    confidence: float
    valid_time: datetime
    data_quality: DataQuality
    constraints: list[str] = []


def evaluate_cell(
    cell: GridCell,
    risk_result: RiskResult,
    *,
    confidence: float,
    valid_time: datetime,
    data_quality: DataQuality,
    constraints: list[str] | None = None,
) -> RiskCellResult:
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")

    return RiskCellResult(
        cell_id=cell.cell_id,
        geometry_geojson=cell.to_geojson()["geometry"],
        risk_score=risk_result.score,
        risk_level=risk_result.level,
        confidence=confidence,
        valid_time=valid_time,
        data_quality=data_quality,
        constraints=constraints or [],
    )
