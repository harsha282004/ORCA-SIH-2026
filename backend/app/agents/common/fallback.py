"""LIVE -> CACHED fallback orchestration — architecture.md §16.

Shared by the Weather and Oceanographic agents (both wrap an
Open-Meteo-style ``app.data.base.SourceAdapter`` with an identical
fallback shape). The GIS agent's "fallback" is a different shape (static
GIS *dataset acquisition status*, not a live per-request fetch) and does
not use this module.

The third tier — STATIC/DEMO — is deliberately NOT handled here: what
"static" means differs per source (a weather demo snapshot vs. a marine
demo snapshot), and, critically, architecture.md §16a requires that tier
to be used ONLY in DEMO mode (LIVE mode must go straight to
NO_SAFE_RECOMMENDATION rather than silently using synthetic data as if it
were current). That mode-gating decision belongs to each concrete agent,
not this shared orchestrator.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.agents.common.cache import AgentCache, build_cache_key, time_bucket_hourly
from app.data.base import SourceAdapter, SourceAdapterError
from app.fabric.fabric import ingest
from app.llm.provider import retry_once_with_backoff
from app.models.contracts import Mode, NormalizedObservation, SourceTier


class AllSourcesUnavailableError(Exception):
    """LIVE failed and no acceptable CACHE entry exists. The caller decides
    what happens next (static/demo fallback if `mode == "demo"`, or a
    failed AgentResult in `mode == "live"` — architecture.md §16a).
    """


def fetch_with_fallback(
    *,
    adapter: SourceAdapter,
    cache: AgentCache,
    namespace: str,
    latitude: float,
    longitude: float,
    requested_time: datetime,
    max_staleness: timedelta,
    mode: Mode,
) -> tuple[list[NormalizedObservation], SourceTier]:
    """Returns (observations, source_tier) where source_tier is "live" or
    "cached". Raises AllSourcesUnavailableError if both fail.
    """
    cache_key = build_cache_key(
        namespace=namespace, latitude=latitude, longitude=longitude, time_bucket=time_bucket_hourly(requested_time)
    )

    def _fetch_and_parse() -> list[NormalizedObservation]:
        raw = adapter.fetch(latitude=latitude, longitude=longitude)
        return adapter.parse(raw, mode=mode)

    live_error: SourceAdapterError | None = None
    try:
        # architecture.md §38: "Retry once w/ backoff" — a general failure
        # policy, not an LLM-specific one; reused verbatim from
        # `app.llm.provider` rather than a second retry implementation.
        # Phase 11 QA measured this namespace's live source (Open-Meteo
        # Marine) returning HTTP 429 "Too many concurrent requests" under
        # this endpoint's own 16-way concurrent sample fetch
        # (`app.agents.environmental_provider`) — a transient condition a
        # single retry-with-backoff resolves, verified by repeated live runs.
        observations = retry_once_with_backoff(_fetch_and_parse, backoff_seconds=1.0)
        batch = ingest(observations, requested_time=requested_time, max_staleness=max_staleness)
        cache.set(cache_key, batch.observations)
        return batch.observations, "live"
    except SourceAdapterError as exc:
        # Fall through to cache — a network/parse failure is expected and
        # recoverable — but `SourceAdapterError`'s own docstring promises
        # "never silently swallowed": the reason is carried forward into
        # whichever outcome follows (a "no cache entry" error below, or the
        # caller's degraded-to-synthetic `AgentResult.warnings`), not
        # dropped here (Phase 11 QA finding — this bare `pass` previously
        # discarded it entirely, making an intermittent live-API failure
        # indistinguishable from any other cause without live debugging).
        live_error = exc

    cached = cache.get(cache_key)
    if cached is not None:
        # Re-run the Temporal Validity Gate against the CURRENT requested
        # time — a cache hit never silently inherits its write-time
        # validity status (architecture.md Phase 4 task spec §17): data
        # that was VALID when cached may now be STALE or EXPIRED, and must
        # be reported as such, never quietly promoted back to VALID.
        batch = ingest(cached, requested_time=requested_time, max_staleness=max_staleness)
        return batch.observations, "cached"

    reason = f" ({live_error})" if live_error is not None else ""
    raise AllSourcesUnavailableError(f"{namespace}: live fetch failed{reason} and no cache entry for key {cache_key!r}")
