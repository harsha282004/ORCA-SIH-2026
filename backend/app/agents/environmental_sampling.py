"""Shared bounded environmental sampling — extracted from
`app.api.v1.layers`'s own `_sample_environment` (Phase 2) so a second
consumer (Phase 3's fishing-intelligence engine, `app.fishing.engine`) can
reuse the EXACT same bounded-sampling strategy without either duplicating
it or importing a presentation-layer module from a domain module.

Identical behavior to the code this replaces — a pure relocation, not a
rewrite. `app/api/v1/layers.py` now imports from here instead.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.agents.environmental_provider import generate_sample_points
from app.agents.oceanographic.agent import OceanographicIntelligenceAgent
from app.agents.weather.agent import WeatherIntelligenceAgent
from app.models.contracts import AgentResult
from app.models.geo import BBox


class SampleSite(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    latitude: float
    longitude: float
    weather: AgentResult
    marine: AgentResult


def sample_environment_grid(
    *,
    bbox: BBox,
    requested_time: datetime,
    samples_per_axis: int,
    max_concurrent_requests: int,
    weather_agent: WeatherIntelligenceAgent,
    oceanographic_agent: OceanographicIntelligenceAgent,
) -> list[SampleSite]:
    """The SAME bounded `samples_per_axis` x `samples_per_axis` sampling
    strategy `AgentBackedEnvironmentalProvider` uses for routing
    (architecture.md Phase 4 task spec §13 — a live call per grid cell is
    explicitly disallowed) — reused via the public `generate_sample_points`
    helper, not duplicated. Each Weather/Oceanographic agent call already
    goes through its own LIVE->CACHED->STATIC fallback and Redis cache
    (app.agents.common.cache), so repeated calls across a short window
    (e.g. the map's oceanography layer and the fishing engine, moments
    apart) mostly hit cache rather than issuing new live HTTP requests.
    """
    points = sorted(generate_sample_points(bbox, samples_per_axis=samples_per_axis))

    def fetch(point: tuple[float, float]) -> SampleSite:
        latitude, longitude = point
        weather = weather_agent.get_weather(latitude=latitude, longitude=longitude, requested_time=requested_time)
        marine = oceanographic_agent.get_marine(latitude=latitude, longitude=longitude, requested_time=requested_time)
        return SampleSite(latitude=latitude, longitude=longitude, weather=weather, marine=marine)

    max_workers = max(1, min(max_concurrent_requests, len(points)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, points))
