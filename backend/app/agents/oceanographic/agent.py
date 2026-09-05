"""Oceanographic Intelligence Agent — architecture.md §10.

Identical fallback shape to the Weather Intelligence Agent (see
`app.agents.weather.agent` for the fully-annotated version) — wraps
`app.data.open_meteo_marine.OpenMeteoMarineAdapter`, unchanged. This
module contains no marine-data parsing of its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.common.cache import AgentCache
from app.agents.common.fallback import AllSourcesUnavailableError, fetch_with_fallback
from app.agents.common.result import build_agent_result, build_failed_agent_result
from app.agents.oceanographic.static_fallback import static_marine_observations
from app.config import Settings, get_settings
from app.data.open_meteo_marine import REQUIRED_HOURLY_PARAMETERS, OpenMeteoMarineAdapter
from app.fabric.spatial import validate_point
from app.models.contracts import AgentResult
from app.services.cache import get_client as get_redis_client

NAMESPACE = "marine"


class OceanographicIntelligenceAgent:
    def __init__(
        self,
        *,
        adapter: OpenMeteoMarineAdapter | None = None,
        cache: AgentCache | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._adapter = adapter or OpenMeteoMarineAdapter(
            base_url=self._settings.open_meteo_marine_base_url, timeout_seconds=self._settings.http_timeout_seconds
        )
        self._cache = cache or AgentCache(_redis_client_or_none(), ttl_seconds=self._settings.marine_cache_ttl_seconds)

    def get_marine(self, *, latitude: float, longitude: float, requested_time: datetime | None = None) -> AgentResult:
        validate_point(latitude, longitude)
        requested_time = requested_time or datetime.now(timezone.utc)
        mode = self._settings.orca_mode
        max_staleness = timedelta(minutes=self._settings.marine_max_staleness_minutes)

        try:
            observations, source_tier = fetch_with_fallback(
                adapter=self._adapter,
                cache=self._cache,
                namespace=NAMESPACE,
                latitude=latitude,
                longitude=longitude,
                requested_time=requested_time,
                max_staleness=max_staleness,
                mode=mode,
            )
        except AllSourcesUnavailableError as exc:
            if mode == "demo":
                observations = static_marine_observations(latitude=latitude, longitude=longitude, requested_time=requested_time)
                return build_agent_result(
                    observations=observations,
                    mode=mode,
                    latitude=latitude,
                    longitude=longitude,
                    requested_time=requested_time,
                    max_staleness=max_staleness,
                    expected_parameter_count=len(REQUIRED_HOURLY_PARAMETERS),
                    source_tier_override="synthetic",
                    status="degraded",
                    warnings=["DEMO DATA / SIMULATION — NOT LIVE DATA: live and cached marine data unavailable"],
                )
            return build_failed_agent_result(
                mode=mode, latitude=latitude, longitude=longitude, requested_time=requested_time, errors=[str(exc)]
            )

        return build_agent_result(
            observations=observations,
            mode=mode,
            latitude=latitude,
            longitude=longitude,
            requested_time=requested_time,
            max_staleness=max_staleness,
            expected_parameter_count=len(REQUIRED_HOURLY_PARAMETERS),
            source_tier_override=source_tier,
        )


def _redis_client_or_none():
    try:
        return get_redis_client()
    except Exception:  # noqa: BLE001 — client construction is lazy and local; never let it crash agent setup
        return None
