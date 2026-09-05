"""Weather Intelligence Agent — architecture.md §10.

    request
       |
       v
    validate coordinates            (reuses app.fabric.spatial.validate_point)
       |
       v
    LIVE  (app.data.open_meteo_weather.OpenMeteoWeatherAdapter, unchanged)
       | failure
       v
    CACHED (Redis, app.agents.common.cache)
       | failure
       v
    STATIC/DEMO  (app.agents.weather.static_fallback — DEMO mode only, §16a)
       | failure
       v
    structured failure (AgentResult(status="failed"))

No natural-language generation. No LLM. Reuses Phase 1's adapter,
normalization, and Temporal Validity Gate verbatim — this module contains
no Open-Meteo parsing of its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.common.cache import AgentCache
from app.agents.common.fallback import AllSourcesUnavailableError, fetch_with_fallback
from app.agents.common.result import build_agent_result, build_failed_agent_result
from app.agents.weather.static_fallback import static_weather_observations
from app.config import Settings, get_settings
from app.data.open_meteo_weather import REQUIRED_HOURLY_PARAMETERS, OpenMeteoWeatherAdapter
from app.fabric.spatial import validate_point
from app.models.contracts import AgentResult
from app.services.cache import get_client as get_redis_client

NAMESPACE = "weather"


class WeatherIntelligenceAgent:
    def __init__(
        self,
        *,
        adapter: OpenMeteoWeatherAdapter | None = None,
        cache: AgentCache | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._adapter = adapter or OpenMeteoWeatherAdapter(
            base_url=self._settings.open_meteo_weather_base_url, timeout_seconds=self._settings.http_timeout_seconds
        )
        self._cache = cache or AgentCache(_redis_client_or_none(), ttl_seconds=self._settings.weather_cache_ttl_seconds)

    def get_weather(self, *, latitude: float, longitude: float, requested_time: datetime | None = None) -> AgentResult:
        validate_point(latitude, longitude)
        requested_time = requested_time or datetime.now(timezone.utc)
        mode = self._settings.orca_mode
        max_staleness = timedelta(minutes=self._settings.weather_max_staleness_minutes)

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
                observations = static_weather_observations(latitude=latitude, longitude=longitude, requested_time=requested_time)
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
                    warnings=["DEMO DATA / SIMULATION — NOT LIVE DATA: live and cached weather unavailable"],
                )
            # architecture.md §16a: LIVE mode must never fall through to
            # synthetic data — a structured failure, not a fabricated result.
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
    except Exception:  # noqa: BLE001 — constructing the client is local/lazy and shouldn't fail, but never let cache setup crash agent construction
        return None
