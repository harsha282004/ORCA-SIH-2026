"""ROUTING INTEGRATION tests — architecture.md Phase 4 task spec, final
section: agent-backed risk/hazard providers actually reaching the Risk
Engine and influencing A*'s route selection, with hard-geofence/no-route
semantics unchanged from Phase 3. No real network access — Weather/
Oceanographic agents are stubbed with location-dependent responses so a
"hazardous corridor" can be constructed deterministically.
"""
from datetime import datetime, timezone

import pytest
from shapely.geometry import Polygon

from app.agents.environmental_provider import AgentBackedEnvironmentalProvider
from app.gis.geofence import Geofence, GeofenceCategory
from app.gis.grid import GridCell
from app.models.contracts import AgentResult
from app.models.geo import BBox
from app.routing.engine import calculate_route
from app.routing.errors import NoRouteFoundError, OriginValidationError
from app.routing.models import Coordinate, RouteRequest

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
BBOX = BBox(min_lat=12.0, min_lon=74.0, max_lat=12.3, max_lon=74.3)

CALM_WEATHER = {"wind_speed_10m": 1.0, "weathercode": 1, "temperature_2m": 27.0, "wind_direction_10m": 200.0, "precipitation": 0.0}
SEVERE_WEATHER = {"wind_speed_10m": 25.0, "weathercode": 99, "temperature_2m": 27.0, "wind_direction_10m": 200.0, "precipitation": 5.0}
CALM_MARINE = {"wave_height": 0.3, "wave_period": 6.0, "wave_direction": 200.0, "sea_surface_temperature": 28.0, "ocean_current_velocity": 0.1, "ocean_current_direction": 180.0}
SEVERE_MARINE = {"wave_height": 4.0, "wave_period": 6.0, "wave_direction": 200.0, "sea_surface_temperature": 28.0, "ocean_current_velocity": 0.1, "ocean_current_direction": 180.0}


def make_result(data: dict, *, status="ok") -> AgentResult:
    return AgentResult(
        status=status, data=data, evidence=[], confidence=1.0, source_tier="live",
        timestamp=NOW, spatial_extent={"type": "Point", "coordinates": [74.0, 12.0]},
        temporal_validity={"valid_from": None, "valid_to": None, "is_forecast": True},
        mode="demo", temporal_validity_status="VALID",
    )


# A localized square patch — NOT spanning the full latitude range, unlike
# a longitude-only band would (that would be an impassable "wall" a
# west-to-east route could never detour around, the same mistake Phase 3
# caught with a full-height land fixture). Sized (0.10deg ~11km) wider
# than one sample spacing at samples_per_axis=6 (~0.05deg) so the sampling
# grid is guaranteed to actually capture it, not straddle around it.
_PATCH_LAT = (12.10, 12.20)
_PATCH_LON = (74.10, 74.20)


def _in_hazard_patch(latitude: float, longitude: float) -> bool:
    return _PATCH_LAT[0] <= latitude <= _PATCH_LAT[1] and _PATCH_LON[0] <= longitude <= _PATCH_LON[1]


class PatchDependentWeatherAgent:
    """Returns SEVERE weather inside a localized patch, CALM elsewhere —
    a hazardous area a diagonal route can detour around (north or south),
    not an unavoidable full-height wall.
    """

    def get_weather(self, *, latitude, longitude, requested_time=None):
        if _in_hazard_patch(latitude, longitude):
            return make_result(SEVERE_WEATHER)
        return make_result(CALM_WEATHER)


class PatchDependentMarineAgent:
    def get_marine(self, *, latitude, longitude, requested_time=None):
        if _in_hazard_patch(latitude, longitude):
            return make_result(SEVERE_MARINE)
        return make_result(CALM_MARINE)


class UniformWeatherAgent:
    def __init__(self, data: dict):
        self._data = data

    def get_weather(self, *, latitude, longitude, requested_time=None):
        del latitude, longitude, requested_time
        return make_result(self._data)


class UniformMarineAgent:
    def __init__(self, data: dict):
        self._data = data

    def get_marine(self, *, latitude, longitude, requested_time=None):
        del latitude, longitude, requested_time
        return make_result(self._data)


class NoGeofenceGISAgent:
    def nearest_hard_geofence_distance_km(self, latitude, longitude, **kwargs):
        del latitude, longitude, kwargs
        return None


def test_agent_backed_risk_provider_reaches_risk_engine() -> None:
    """Environmental values from the (stubbed) agents must actually change
    the risk score the Risk Engine computes — not a flat placeholder.
    """
    provider_calm = AgentBackedEnvironmentalProvider(
        weather_agent=UniformWeatherAgent(CALM_WEATHER), oceanographic_agent=UniformMarineAgent(CALM_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=1,
    )
    provider_calm.prepare(BBOX)

    provider_severe = AgentBackedEnvironmentalProvider(
        weather_agent=UniformWeatherAgent(SEVERE_WEATHER), oceanographic_agent=UniformMarineAgent(SEVERE_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=1,
    )
    provider_severe.prepare(BBOX)

    cell = GridCell(cell_id="x", row=0, col=0, geometry=Polygon([(74.1, 12.1), (74.11, 12.1), (74.11, 12.11), (74.1, 12.11)]), centroid_lat=12.1, centroid_lon=74.1)

    assert provider_severe.risk_provider(cell) > provider_calm.risk_provider(cell)
    assert provider_severe.hazard_provider(cell) > provider_calm.hazard_provider(cell)


def test_hazardous_corridor_costs_more_and_route_avoids_it() -> None:
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=PatchDependentWeatherAgent(), oceanographic_agent=PatchDependentMarineAgent(),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=6,
    )
    provider.prepare(BBOX)

    # Origin/destination straddle the hazard patch diagonally, at the same
    # latitude the patch is centered on — a direct path would cut straight
    # through it; a lower-cost path detours around (north or south).
    request = RouteRequest(origin=Coordinate(latitude=12.15, longitude=74.02), destination=Coordinate(latitude=12.15, longitude=74.28))
    result = calculate_route(
        request, bbox=BBOX, geofences=[], risk_provider=provider.risk_provider, hazard_provider=provider.hazard_provider,
        temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="live",
    )

    # The route must avoid the hazardous patch in its path cells, having
    # detoured around it (north or south) rather than cutting through.
    patch_cells = [c for c in result.path_cells if _in_hazard_patch(c.latitude, c.longitude)]
    assert len(patch_cells) == 0, "route passed straight through the hazardous patch"
    assert result.feasibility_status == "FEASIBLE"


def test_safe_corridor_remains_preferred_when_no_hazard_present() -> None:
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=UniformWeatherAgent(CALM_WEATHER), oceanographic_agent=UniformMarineAgent(CALM_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=2,
    )
    provider.prepare(BBOX)

    request = RouteRequest(origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28))
    result = calculate_route(
        request, bbox=BBOX, geofences=[], risk_provider=provider.risk_provider, hazard_provider=provider.hazard_provider,
        temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="live",
    )
    # With uniformly calm conditions, the direct diagonal-ish path should
    # be taken (no reason to detour) — a sanity check that agent-backed
    # data doesn't introduce spurious detours when there's no hazard.
    assert result.feasibility_status == "FEASIBLE"
    assert result.metrics.average_risk_score is not None
    assert result.metrics.average_risk_score < 0.2


def test_hard_geofence_remains_impossible_with_agent_backed_providers() -> None:
    land = Geofence(
        id="land", name="land", category=GeofenceCategory.LAND, is_authoritative=False, source="fixture",
        geometry={"type": "Polygon", "coordinates": [[[74.0, 12.14], [74.3, 12.14], [74.3, 12.16], [74.0, 12.16], [74.0, 12.14]]]},
    )
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=UniformWeatherAgent(CALM_WEATHER), oceanographic_agent=UniformMarineAgent(CALM_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=2,
    )
    provider.prepare(BBOX)

    request = RouteRequest(origin=Coordinate(latitude=12.02, longitude=74.15), destination=Coordinate(latitude=12.28, longitude=74.15))
    with pytest.raises(NoRouteFoundError):
        calculate_route(
            request, bbox=BBOX, geofences=[land], risk_provider=provider.risk_provider, hazard_provider=provider.hazard_provider,
            temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="live",
        )


def test_no_route_semantics_unchanged_destination_blocked_before_astar() -> None:
    land = Geofence(
        id="land2", name="land2", category=GeofenceCategory.LAND, is_authoritative=False, source="fixture",
        geometry={"type": "Polygon", "coordinates": [[[74.0, 12.0], [74.3, 12.0], [74.3, 12.05], [74.0, 12.05], [74.0, 12.0]]]},
    )
    provider = AgentBackedEnvironmentalProvider(
        weather_agent=UniformWeatherAgent(CALM_WEATHER), oceanographic_agent=UniformMarineAgent(CALM_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)

    request = RouteRequest(origin=Coordinate(latitude=12.02, longitude=74.15), destination=Coordinate(latitude=12.28, longitude=74.15))
    with pytest.raises(OriginValidationError):
        calculate_route(
            request, bbox=BBOX, geofences=[land], risk_provider=provider.risk_provider, hazard_provider=provider.hazard_provider,
            temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="live",
        )


def test_deterministic_repeated_execution_with_agent_backed_providers() -> None:
    request = RouteRequest(origin=Coordinate(latitude=12.02, longitude=74.02), destination=Coordinate(latitude=12.28, longitude=74.28))

    results = []
    for _ in range(3):
        provider = AgentBackedEnvironmentalProvider(
            weather_agent=PatchDependentWeatherAgent(), oceanographic_agent=PatchDependentMarineAgent(),
            gis_agent=NoGeofenceGISAgent(), samples_per_axis=4,
        )
        provider.prepare(BBOX)
        result = calculate_route(
            request, bbox=BBOX, geofences=[], risk_provider=provider.risk_provider, hazard_provider=provider.hazard_provider,
            temporal_validity="VALID", confidence=0.9, mode="demo", data_quality="live",
        )
        results.append(result)

    distances = {r.metrics.total_distance_km for r in results}
    costs = {r.metrics.total_cost for r in results}
    paths = {tuple((c.row, c.col) for c in r.path_cells) for r in results}
    assert len(distances) == 1
    assert len(costs) == 1
    assert len(paths) == 1


def test_live_mode_failed_agent_never_leaks_fixture_looking_data() -> None:
    """architecture.md §16a: a failed live/cache fetch in LIVE mode must
    never silently present as usable data — the environmental provider's
    "unknown is risky" policy (risk_score=1.0) makes this concrete: a
    failed site is treated as the WORST case, never a calm-looking fixture
    default that could be mistaken for real favorable conditions.
    """
    class FailedWeatherAgent:
        def get_weather(self, *, latitude, longitude, requested_time=None):
            del latitude, longitude, requested_time
            return make_result({}, status="failed")

    provider = AgentBackedEnvironmentalProvider(
        weather_agent=FailedWeatherAgent(), oceanographic_agent=UniformMarineAgent(CALM_MARINE),
        gis_agent=NoGeofenceGISAgent(), samples_per_axis=1,
    )
    provider.prepare(BBOX)

    cell = GridCell(cell_id="x", row=0, col=0, geometry=Polygon([(74.1, 12.1), (74.11, 12.1), (74.11, 12.11), (74.1, 12.11)]), centroid_lat=12.1, centroid_lon=74.1)
    assert provider.risk_provider(cell) == 1.0  # maximally risky, never a calm 0.0-ish default
