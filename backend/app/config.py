"""Central backend configuration.

All values are sourced from environment variables (optionally via a local
.env file). No credentials or secrets are hard-coded here — see
.env.example at the repository root for the recognized variables.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.geo import BBox


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Runtime mode — see architecture.md §16a (LIVE vs DEMO semantics).
    orca_mode: str = "demo"

    # Demo region bounding box — Mangaluru-Udupi coastal Karnataka is fixed
    # by architecture.md §44, but the exact numeric box is NOT frozen there.
    # These defaults are a PROPOSED box (see docs/demo_region.md) awaiting
    # explicit confirmation before any large-scale static-data acquisition
    # is run against it. Live per-request calls (Open-Meteo) are unaffected
    # by that pending confirmation — they are not a bulk/irreversible
    # acquisition and use whatever bbox is currently configured here.
    demo_bbox_min_lat: float = 12.70
    demo_bbox_min_lon: float = 73.50
    demo_bbox_max_lat: float = 13.45
    demo_bbox_max_lon: float = 75.05

    # Open-Meteo — architecture.md §14, primary live sources, no API key required.
    open_meteo_weather_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_marine_base_url: str = "https://marine-api.open-meteo.com/v1/marine"
    http_timeout_seconds: float = 6.0  # matches architecture.md §11b's 6s data-agent timeout

    # Max staleness before the Temporal Validity Gate marks data STALE —
    # architecture.md §16's fallback table: 30 min for wind/weather and
    # waves/currents/SST.
    weather_max_staleness_minutes: int = 30
    marine_max_staleness_minutes: int = 30

    # Where raw source responses are preserved (architecture.md §42's data/raw).
    # Relative to the current working directory — run scripts from the repo root.
    data_raw_dir: str = "data/raw"

    # Phase 4 data agents — Redis cache TTLs (architecture.md §16's 3-tier
    # fallback). Weather/marine TTLs track their own max-staleness windows
    # above; GIS's is longer since geofence/static-dataset status changes
    # far less often than a weather forecast.
    weather_cache_ttl_seconds: int = 1800
    marine_cache_ttl_seconds: int = 1800
    gis_cache_ttl_seconds: int = 86400

    # Bounded environmental sampling for routing (architecture.md Phase 4
    # task spec §13): a `samples_per_axis` x `samples_per_axis` grid of live
    # sample points is fetched per route request — NOT one live call per
    # routing grid cell. 4x4=16 sample points vs. ~1,596 routing cells on
    # the demo bbox is a >100x reduction. See docs/data_agents.md.
    environmental_samples_per_axis: int = 4

    # Bounded concurrency for fetching the sample grid (architecture.md
    # Phase 4 task spec §33's "concurrent source requests" safeguard) — a
    # ThreadPoolExecutor caps how many Weather/Oceanographic HTTP calls run
    # at once, so a larger sample grid doesn't serialize into an
    # impractically slow single HTTP request.
    max_concurrent_agent_requests: int = 16

    # LLM Provider Abstraction Layer config (architecture.md §11a).
    # Phase 0 stores these as placeholders only — no LLM is called yet.
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    # Phase 5 orchestration — multi-turn session persistence (architecture.md §31).
    session_ttl_seconds: int = 3600

    # PostgreSQL / PostGIS
    postgres_db: str = "orca"
    postgres_user: str = "orca"
    postgres_password: str = "change_me"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # CORS — comma-separated list of allowed frontend origins for local dev.
    cors_origins_raw: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def demo_bbox(self) -> BBox:
        return BBox(
            min_lat=self.demo_bbox_min_lat,
            min_lon=self.demo_bbox_min_lon,
            max_lat=self.demo_bbox_max_lat,
            max_lon=self.demo_bbox_max_lon,
        )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
