"""Alert Engine data contracts — architecture.md §29.

Five of the architecture's seven named hazard rows are computable from data
this system actually fetches; the other two are honestly omitted, never
faked (see `app.alerts.engine` module docstring for why):

    wave, wind, lightning_thunderstorm_proxy, restricted_zone_distance,
    risk_threshold                                    <- implemented
    cyclone_proxy, route_entering_prohibited_zone      <- NOT implemented
    (no pressure/gust/persistence signals fetched;      (only meaningful
     see app.agents.common.risk_inputs's own honest       for an actual
     documented limitation)                               route, not a
                                                           region snapshot)
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

HazardType = Literal["wave", "wind", "lightning_thunderstorm_proxy", "restricted_zone_distance", "risk_threshold"]
AlertState = Literal["New", "Updated", "Escalated", "Resolved"]

# architecture.md §29: "Mechanics: Hazard Detection -> Deduplication ->
# Severity-change check -> Send/Update Alert." A hazard whose normalized
# severity (the SAME [0,1] scale app.risk.components' functions already
# produce) is at or above this bar is alert-worthy; below it, it is simply
# not reported (never a fabricated "all clear" claim about a channel this
# module doesn't check — see HazardType's docstring on what's omitted).
ALERT_SEVERITY_THRESHOLD = 0.5


class Alert(BaseModel):
    hazard_type: HazardType
    state: AlertState
    severity: float  # normalized [0, 1] — same scale as the Risk Engine's own components
    message: str


class AlertsResult(BaseModel):
    region_key: str
    latitude: float
    longitude: float
    alerts: list[Alert]
    # architecture.md's no-fabrication rule: an EMPTY `alerts` list must
    # never be misread as "conditions are known to be clear" when they were
    # actually never resolvable at all. True whenever the Weather/
    # Oceanographic data needed to evaluate overall risk was unavailable —
    # the composite risk-threshold hazard is skipped, never guessed.
    data_unavailable: bool = False
