"""Agent-backed environmental providers for Phase 3's routing engine —
architecture.md Phase 4 task spec §12/§13/§26.

    Routing Grid
          |
    grid cell center
          |
    Weather Agent + Oceanographic Agent   (bounded spatial SAMPLE grid, not per-cell)
          |
    Phase 2 Risk Engine (compute_risk) + hazard proxy (lightning_thunderstorm_proxy)
          |
    risk_provider(cell) / hazard_provider(cell)   <-- app.routing.grid.EnvironmentalScoreProvider
          |
    A* edge costs (app.routing.astar — UNCHANGED)

**Why bounded sampling, not one live call per grid cell**: the demo grid is
~1,596 cells (Phase 3, measured). A live HTTP call per cell is explicitly
disallowed. Instead, a small deterministic `samples_per_axis` x
`samples_per_axis` grid of SAMPLE POINTS (default 4x4 = 16, configurable
via `Settings.environmental_samples_per_axis`) is fetched once per route
calculation via the Weather/Oceanographic agents (each with their own
LIVE->CACHED->STATIC fallback and Redis caching) — a >100x reduction in
live calls. Every routing grid cell is then assigned its NEAREST sample
site's environmental data, via deterministic nearest-neighbor lookup
(Phase 2's own `haversine_km` — reused, not reimplemented). This is
explicitly NOT interpolation: no in-between value is invented, and no
claim of sub-sample-spacing accuracy is made (see docs/data_agents.md).

Geometry-based risk factors (`restricted_zone_distance`, `coast_distance`)
require no network call, so they are computed EXACTLY per grid cell via
the GIS agent, not sampled.

**Missing/failed data policy**: if a sample site's weather or marine data
is unusable (`AgentResult.status == "failed"`, i.e. LIVE mode with no
live/cached source and no risk of silently using synthetic data), that
site is treated as maximally risky (risk_score=1.0), not zero — an
"unknown is risky, not safe" policy, since Phase 2's Risk Engine itself
refuses to compute a score from incomplete inputs
(`MissingRiskComponentError`) and A* needs some deterministic numeric
score per cell to keep functioning.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.agents.common.result import worst_temporal_validity_status
from app.agents.common.risk_inputs import InsufficientRiskDataError, build_normalized_risk_components
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.config import get_settings
from app.gis.distance import haversine_km
from app.gis.grid import GridCell
from app.models.contracts import AgentResult, TemporalValidityStatus
from app.models.geo import BBox
from app.risk.config import RiskConfig, get_risk_config
from app.risk.engine import compute_risk
from app.risk.hazard_proxies import lightning_thunderstorm_proxy

_UNAVAILABLE_RISK_SCORE = 1.0  # "unknown is risky, not safe" — see module docstring
_UNAVAILABLE_HAZARD_SCORE = 0.0  # no thunderstorm signal to report if there is no weathercode at all


def generate_sample_points(bbox: BBox, *, samples_per_axis: int) -> list[tuple[float, float]]:
    """Deterministic, cell-centered `samples_per_axis` x `samples_per_axis`
    grid of coordinates spanning `bbox`, in a fixed row-major order.
    """
    if samples_per_axis < 1:
        raise ValueError(f"samples_per_axis must be >= 1, got {samples_per_axis}")

    lat_step = (bbox.max_lat - bbox.min_lat) / samples_per_axis
    lon_step = (bbox.max_lon - bbox.min_lon) / samples_per_axis

    points: list[tuple[float, float]] = []
    for i in range(samples_per_axis):
        latitude = bbox.min_lat + (i + 0.5) * lat_step
        for j in range(samples_per_axis):
            longitude = bbox.min_lon + (j + 0.5) * lon_step
            points.append((latitude, longitude))
    return points


def _site_risk_and_hazard(
    weather: AgentResult,
    marine: AgentResult,
    *,
    latitude: float,
    longitude: float,
    gis_agent: GISGeofencingAgent,
    risk_config: RiskConfig,
) -> tuple[float, float]:
    """Routing's own missing-data policy — "unknown is risky, not safe"
    (see module docstring) — applied around the shared component builder
    (`app.agents.common.risk_inputs`, also used by Phase 5's Risk &
    Suitability Agent, which applies a DIFFERENT policy: surfacing
    missing data to the Safety Guard instead of substituting a score).
    """
    try:
        components = build_normalized_risk_components(
            weather, marine, latitude=latitude, longitude=longitude, gis_agent=gis_agent
        )
    except InsufficientRiskDataError:
        return _UNAVAILABLE_RISK_SCORE, _UNAVAILABLE_HAZARD_SCORE

    risk_result = compute_risk(components, risk_config.risk_weights, risk_config.risk_thresholds)
    hazard_score = lightning_thunderstorm_proxy(weather.data["weathercode"])
    return risk_result.score, hazard_score


class AgentBackedEnvironmentalProvider:
    """Built once per route calculation (`prepare(bbox)`), then handed to
    `app.routing.engine.calculate_route` as `risk_provider`/`hazard_provider`
    — satisfying `app.routing.grid.EnvironmentalScoreProvider` exactly, so
    `app.routing.astar`/`costs`/`grid` require zero changes.
    """

    def __init__(
        self,
        *,
        weather_agent: WeatherIntelligenceAgent | None = None,
        oceanographic_agent: OceanographicIntelligenceAgent | None = None,
        gis_agent: GISGeofencingAgent | None = None,
        samples_per_axis: int | None = None,
        requested_time: datetime | None = None,
        risk_config: RiskConfig | None = None,
    ):
        settings = get_settings()
        self._weather_agent = weather_agent or WeatherIntelligenceAgent()
        self._oceanographic_agent = oceanographic_agent or OceanographicIntelligenceAgent()
        self._gis_agent = gis_agent or GISGeofencingAgent()
        self._samples_per_axis = samples_per_axis or settings.environmental_samples_per_axis
        self._max_concurrent_requests = settings.max_concurrent_agent_requests
        self._requested_time = requested_time or datetime.now(timezone.utc)
        self._risk_config = risk_config or get_risk_config()
        self._sites: list[tuple[float, float, float, float]] = []  # (lat, lon, risk_score, hazard_score)
        self.overall_temporal_validity: TemporalValidityStatus = "MISSING_TIMESTAMP"
        self.overall_confidence: float = 0.0
        # True if ANY sample site had to fall back to synthetic/demo data
        # (§16a: static/demo data must never silently pass as live) — used
        # by callers (e.g. the /api/v1/route endpoint) to report an honest
        # overall `data_quality`, independent of `Settings.orca_mode`
        # (session type) which is a separate concern from actual data
        # provenance (architecture.md §16a; see also Phase 1's
        # NormalizedObservation.is_live discipline).
        self.used_synthetic_fallback: bool = False

    def prepare(self, bbox: BBox) -> None:
        """Fetches the bounded sample grid, one Weather+Oceanographic call
        pair per sample point, run with bounded concurrency (architecture.md
        Phase 4 task spec §33) rather than sequentially — measured
        sequential fetch time for a 3x3 sample grid in this development
        environment was ~98s (see docs/data_agents.md §Performance),
        impractical for a synchronous HTTP endpoint; concurrency is a
        genuine mitigation, not a workaround, since each sample fetch is
        fully independent.

        Must be called once before this provider is passed to
        `calculate_route`. Sample points are sorted by (lat, lon) first, and
        `ThreadPoolExecutor.map` preserves input order in its results
        regardless of completion order — so `self._sites` ends up in a
        fixed, deterministic order regardless of which request happens to
        finish first.
        """
        sample_points = sorted(generate_sample_points(bbox, samples_per_axis=self._samples_per_axis))

        def fetch_site(point: tuple[float, float]) -> tuple[float, float, float, float, AgentResult, AgentResult]:
            latitude, longitude = point
            weather = self._weather_agent.get_weather(latitude=latitude, longitude=longitude, requested_time=self._requested_time)
            marine = self._oceanographic_agent.get_marine(latitude=latitude, longitude=longitude, requested_time=self._requested_time)
            risk_score, hazard_score = _site_risk_and_hazard(
                weather, marine, latitude=latitude, longitude=longitude, gis_agent=self._gis_agent, risk_config=self._risk_config
            )
            return latitude, longitude, risk_score, hazard_score, weather, marine

        max_workers = max(1, min(self._max_concurrent_requests, len(sample_points)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            fetched = list(executor.map(fetch_site, sample_points))

        self._sites = [(lat, lon, risk, hazard) for lat, lon, risk, hazard, _w, _m in fetched]
        all_results = [r for _l, _o, _r, _h, w, m in fetched for r in (w, m)]
        self.overall_temporal_validity = worst_temporal_validity_status([r.temporal_validity_status for r in all_results])
        self.overall_confidence = min((r.confidence for r in all_results), default=0.0)
        self.used_synthetic_fallback = any(r.source_tier == "synthetic" for r in all_results)

    def _nearest_site(self, latitude: float, longitude: float) -> tuple[float, float]:
        if not self._sites:
            raise RuntimeError("AgentBackedEnvironmentalProvider.prepare(bbox) must be called before use")
        _lat, _lon, risk_score, hazard_score = min(
            self._sites, key=lambda site: haversine_km(latitude, longitude, site[0], site[1])
        )
        return risk_score, hazard_score

    def risk_provider(self, cell: GridCell) -> float:
        risk_score, _hazard_score = self._nearest_site(cell.centroid_lat, cell.centroid_lon)
        return risk_score

    def hazard_provider(self, cell: GridCell) -> float:
        _risk_score, hazard_score = self._nearest_site(cell.centroid_lat, cell.centroid_lon)
        return hazard_score
