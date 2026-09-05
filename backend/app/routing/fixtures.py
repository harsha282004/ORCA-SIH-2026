"""Demo routing fixtures — architecture.md §16a's DEMO MODE semantics
("UI must visibly indicate DEMO DATA... wherever such data is used").

Phase 1 never acquired the real Natural Earth coastline / WDPA protected-
area datasets (see docs/demo_region.md) — there is no live per-cell
environmental grid either (that is Phase 4's Weather/Oceanographic Agent
territory). So the `POST /api/v1/route` endpoint's default inputs are
explicit, labeled fixtures, not an attempt to simulate real conditions.
`RouteResult.data_quality` is always "fixture" while these are in use —
never silently presented as live.

When real coastline/geofence data and a live per-cell Marine Data Fabric
lookup exist, they satisfy the exact same `Geofence` /
`EnvironmentalScoreProvider` interfaces these fixtures implement — no
change to the routing engine, A*, or cost function is required.
"""
from __future__ import annotations

from app.gis.geofence import Geofence, GeofenceCategory
from app.gis.grid import GridCell

# A schematic land strip along the demo bbox's eastern edge — roughly where
# the real Karnataka coastline runs, so demo routes look plausible, but
# this is NOT the real coastline. source="fixture" makes that explicit and
# machine-checkable, matching architecture.md §25's is_authoritative
# discipline (False here, always).
DEMO_LAND_FIXTURE = Geofence(
    id="demo-land-fixture",
    name="Demo coastline fixture (NOT real Natural Earth data)",
    category=GeofenceCategory.LAND,
    geometry={
        "type": "Polygon",
        "coordinates": [[[74.80, 12.70], [75.05, 12.70], [75.05, 13.45], [74.80, 13.45], [74.80, 12.70]]],
    },
    is_authoritative=False,
    source="fixture",
)

DEMO_FIXTURE_GEOFENCES: list[Geofence] = [DEMO_LAND_FIXTURE]


def demo_flat_risk_provider(_cell: GridCell) -> float:
    """A flat, low, clearly-synthetic placeholder — Phase 3 does not compute
    real per-cell risk from live Marine Data Fabric output (no live
    per-cell environmental fetch exists yet). Real risk-aware routing is
    fully implemented and tested (see backend/tests/routing/test_risk_hazard_routing.py)
    against explicit test fixtures; this function only backs the default
    HTTP demo endpoint until Phase 4 wires a real per-cell provider.
    """
    return 0.05


def demo_flat_hazard_provider(_cell: GridCell) -> float:
    return 0.0
