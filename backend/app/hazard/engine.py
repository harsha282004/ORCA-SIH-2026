"""Deterministic hazard detection — Phase 4.

Every threshold below is imported from `app.risk.components`, the EXISTING
Risk Engine's own documented saturation points (architecture.md §22) —
never a new number invented for this phase. A cell/point that saturates a
risk component (wave >= WAVE_SATURATION_M, wind >= WIND_SATURATION_MS) is,
by the Risk Engine's own definition, already being scored as maximally
risky for that factor; Phase 4 simply also surfaces that same fact as a
named, user-facing Hazard object rather than only a hidden number inside a
weighted sum.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.hazard.cyclone import fetch_active_cyclone_hazards, relevant_cyclones
from app.hazard.models import Hazard, HazardSourceStatus
from app.models.contracts import AgentResult
from app.risk.components import WAVE_SATURATION_M, WIND_SATURATION_MS
from app.risk.hazard_proxies import THUNDERSTORM_WMO_CODES

# A documented sub-saturation threshold for an ADVISORY-level (not yet
# DANGER-level) high-wave/high-wind hazard — 70% of the Risk Engine's own
# saturation point, the same "meaningfully elevated but not yet maximal"
# convention `app.risk.engine.classify_risk_level`'s own MODERATE band
# already uses (0.33-0.66 of the [0,1] scale). Never a second, competing
# risk formula — this only decides which Hazard SEVERITY label to attach,
# the risk SCORE itself is untouched.
_ADVISORY_FRACTION = 0.7


def detect_weather_hazards(*, weather: AgentResult, marine: AgentResult, latitude: float, longitude: float) -> list[Hazard]:
    hazards: list[Hazard] = []
    now = datetime.now(timezone.utc)

    if marine.status != "failed":
        wave_height = marine.data.get("wave_height")
        if wave_height is not None:
            if wave_height >= WAVE_SATURATION_M:
                hazards.append(_wave_hazard(wave_height, "DANGER", latitude, longitude, marine))
            elif wave_height >= WAVE_SATURATION_M * _ADVISORY_FRACTION:
                hazards.append(_wave_hazard(wave_height, "ADVISORY", latitude, longitude, marine))

    if weather.status != "failed":
        wind_speed = weather.data.get("wind_speed_10m")
        if wind_speed is not None:
            if wind_speed >= WIND_SATURATION_MS:
                hazards.append(_wind_hazard(wind_speed, "DANGER", latitude, longitude, weather))
            elif wind_speed >= WIND_SATURATION_MS * _ADVISORY_FRACTION:
                hazards.append(_wind_hazard(wind_speed, "ADVISORY", latitude, longitude, weather))

        weathercode = weather.data.get("weathercode")
        if weathercode is not None and int(weathercode) in THUNDERSTORM_WMO_CODES:
            hazards.append(
                Hazard(
                    hazard_type="THUNDERSTORM_PROXY",
                    severity="WARNING",
                    title="Thunderstorm (weather-code proxy)",
                    description=(
                        f"WMO weather code {int(weathercode)} indicates thunderstorm conditions in the forecast "
                        "model. This is a coarse PROXY, not real-time lightning-strike detection — DAMINI (IITM/IMD) "
                        "remains the authoritative source and is not integrated (see docs/PHASE_4_..._REPORT.md §3)."
                    ),
                    latitude=latitude, longitude=longitude,
                    observed_at=weather.timestamp,
                    source="Open-Meteo weather code (app.risk.hazard_proxies.lightning_thunderstorm_proxy)",
                    is_authoritative=False,
                    is_proxy=True,
                    freshness="FORECAST",
                    confidence=weather.confidence,
                )
            )

    return hazards


def _wave_hazard(value: float, severity: str, lat: float, lon: float, marine: AgentResult) -> Hazard:
    return Hazard(
        hazard_type="HIGH_WAVES", severity=severity, title=f"{'High' if severity == 'ADVISORY' else 'Dangerous'} wave conditions",
        description=f"Wave height {value:.2f} m ({'above' if severity == 'DANGER' else 'approaching'} the Risk Engine's {WAVE_SATURATION_M:.1f} m saturation threshold).",
        latitude=lat, longitude=lon, observed_at=marine.timestamp,
        source="Open-Meteo Marine (app.risk.components.WAVE_SATURATION_M threshold)", is_authoritative=False, is_proxy=False,
        freshness="FORECAST", confidence=marine.confidence,
    )


def _wind_hazard(value: float, severity: str, lat: float, lon: float, weather: AgentResult) -> Hazard:
    return Hazard(
        hazard_type="HIGH_WIND", severity=severity, title=f"{'High' if severity == 'ADVISORY' else 'Dangerous'} wind conditions",
        description=f"Wind speed {value:.2f} m/s ({'above' if severity == 'DANGER' else 'approaching'} the Risk Engine's {WIND_SATURATION_MS:.1f} m/s saturation threshold).",
        latitude=lat, longitude=lon, observed_at=weather.timestamp,
        source="Open-Meteo Weather (app.risk.components.WIND_SATURATION_MS threshold)", is_authoritative=False, is_proxy=False,
        freshness="FORECAST", confidence=weather.confidence,
    )


def detect_all_hazards(
    *,
    weather: AgentResult,
    marine: AgentResult,
    latitude: float,
    longitude: float,
    cache=None,
) -> tuple[list[Hazard], list[HazardSourceStatus]]:
    """The single entry point Phase 4's API/orchestration integration calls.
    Returns (hazards, unavailable_sources) — the second list is never
    empty, because at least one hazard category (authoritative lightning)
    is always genuinely unavailable in this deployment (see §3 of the
    Phase 4 report) and must always be disclosed, not omitted once no
    hazard happens to be active.
    """
    hazards = detect_weather_hazards(weather=weather, marine=marine, latitude=latitude, longitude=longitude)

    cyclone_hazards, cyclone_source_tier = fetch_active_cyclone_hazards(cache=cache)
    unavailable: list[HazardSourceStatus] = []

    if cyclone_source_tier == "unavailable":
        unavailable.append(
            HazardSourceStatus(
                hazard_type="CYCLONE", source="GDACS (https://www.gdacs.org/)", is_authoritative=True,
                programmatically_accessible=True,
                status="UNAVAILABLE", reason="GDACS request failed or timed out for this query — treated as unavailable, never as \"no cyclone\".",
            )
        )
    else:
        hazards.extend(relevant_cyclones(cyclone_hazards, latitude=latitude, longitude=longitude))

    unavailable.append(
        HazardSourceStatus(
            hazard_type="THUNDERSTORM_PROXY", source="DAMINI (IITM/IMD) — no public API", is_authoritative=True,
            programmatically_accessible=False, status="UNAVAILABLE",
            reason="No public real-time lightning-detection API exists for this region (audited in Phase 0 and reconfirmed this phase); "
            "the WMO-weather-code thunderstorm proxy above is a forecast-model proxy, not authoritative detection.",
        )
    )

    return hazards, unavailable
