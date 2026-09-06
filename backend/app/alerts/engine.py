"""Alert Engine — architecture.md §29.

    Hazard Detection -> Deduplication -> Severity-change check -> Send/Update Alert
    States: New, Updated, Escalated, Resolved

Every severity value below comes from an EXISTING Risk Engine component
function (`app.risk.components`, `app.risk.hazard_proxies`,
`app.risk.engine.classify_risk_level`) — this module contains no second
copy of that math, only hazard-detection thresholding and New/Updated/
Escalated/Resolved state comparison against the previously-persisted set
(`app.alerts.store.AlertStore`).
"""
from __future__ import annotations

from app.alerts.models import ALERT_SEVERITY_THRESHOLD, Alert, HazardType
from app.models.contracts import AgentResult
from app.risk.components import restricted_zone_distance_risk, wave_risk, wind_risk
from app.risk.config import RiskThresholds
from app.risk.engine import classify_risk_level
from app.risk.hazard_proxies import lightning_thunderstorm_proxy

_LEVEL_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}

_MESSAGES: dict[HazardType, str] = {
    "wave": "High wave conditions detected near this location (normalized severity {severity:.2f}).",
    "wind": "Strong wind conditions detected near this location (normalized severity {severity:.2f}).",
    "lightning_thunderstorm_proxy": (
        "Weather-model thunderstorm indicator triggered (WMO weather-code proxy) — a coarse hazard "
        "proxy, not real-time lightning-strike detection. DAMINI (IITM/IMD) remains the authoritative "
        "real-time lightning-detection reference."
    ),
    "restricted_zone_distance": "This location is close to a restricted/protected zone (normalized severity {severity:.2f}).",
    "risk_threshold": "Overall computed risk for this location is {risk_level} (score {severity:.2f}).",
}


def detect_hazard_severities(
    *,
    weather: AgentResult,
    marine: AgentResult,
    distance_to_hard_geofence_km: float | None,
    overall_risk_score: float,
    overall_risk_level: str,
) -> dict[HazardType, tuple[float, str]]:
    """Returns `{hazard_type: (severity, message)}` for every hazard whose
    normalized severity is at/above `ALERT_SEVERITY_THRESHOLD`.
    """
    detected: dict[HazardType, tuple[float, str]] = {}

    wave_height = marine.data.get("wave_height")
    if wave_height is not None:
        severity = wave_risk(wave_height)
        if severity >= ALERT_SEVERITY_THRESHOLD:
            detected["wave"] = (severity, _MESSAGES["wave"].format(severity=severity))

    wind_speed = weather.data.get("wind_speed_10m")
    if wind_speed is not None:
        severity = wind_risk(wind_speed)
        if severity >= ALERT_SEVERITY_THRESHOLD:
            detected["wind"] = (severity, _MESSAGES["wind"].format(severity=severity))

    weathercode = weather.data.get("weathercode")
    if weathercode is not None:
        severity = lightning_thunderstorm_proxy(weathercode)
        if severity >= ALERT_SEVERITY_THRESHOLD:
            detected["lightning_thunderstorm_proxy"] = (severity, _MESSAGES["lightning_thunderstorm_proxy"])

    if distance_to_hard_geofence_km is not None:
        severity = restricted_zone_distance_risk(distance_to_hard_geofence_km)
        if severity >= ALERT_SEVERITY_THRESHOLD:
            detected["restricted_zone_distance"] = (
                severity,
                _MESSAGES["restricted_zone_distance"].format(severity=severity),
            )

    if overall_risk_level in ("MODERATE", "HIGH"):
        detected["risk_threshold"] = (
            overall_risk_score,
            _MESSAGES["risk_threshold"].format(risk_level=overall_risk_level, severity=overall_risk_score),
        )

    return detected


def diff_alert_states(
    *, previous: dict[str, float], current: dict[HazardType, tuple[float, str]], thresholds: RiskThresholds
) -> tuple[list[Alert], dict[str, float]]:
    """`previous` is the last-persisted `{hazard_type: severity}` for this
    region. Returns `(alerts_to_report_this_call, new_state_to_persist)`.
    A hazard whose severity is materially unchanged since last call is
    dropped entirely (§29: "not repeated identical alerts for one sustained
    hazard") — it still carries forward into `new_state_to_persist` so a
    LATER change is still detected relative to it.
    """
    alerts: list[Alert] = []
    next_state: dict[str, float] = {}

    for hazard_type, (severity, message) in current.items():
        next_state[hazard_type] = severity
        prior_severity = previous.get(hazard_type)

        if prior_severity is None:
            alerts.append(Alert(hazard_type=hazard_type, state="New", severity=severity, message=message))
            continue

        prior_rank = _LEVEL_RANK[classify_risk_level(prior_severity, thresholds)]
        new_rank = _LEVEL_RANK[classify_risk_level(severity, thresholds)]
        if new_rank > prior_rank:
            alerts.append(Alert(hazard_type=hazard_type, state="Escalated", severity=severity, message=message))
        elif abs(severity - prior_severity) > 1e-9:
            alerts.append(Alert(hazard_type=hazard_type, state="Updated", severity=severity, message=message))
        # else: materially unchanged this call -> deliberately not re-reported.

    for hazard_type, _prior_severity in previous.items():
        if hazard_type not in current:
            alerts.append(
                Alert(
                    hazard_type=hazard_type,
                    state="Resolved",
                    severity=0.0,
                    message=f"The previously-reported {hazard_type} hazard is no longer detected at this location.",
                )
            )

    return alerts, next_state
