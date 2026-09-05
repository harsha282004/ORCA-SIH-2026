"""Risk & Suitability Agent — architecture.md §10, §21, §22.

An orchestration-facing wrapper around the EXISTING deterministic Risk
Engine (`app.risk.engine.compute_risk`), confidence combination, and
Fishing Suitability Engine (`app.suitability.engine.evaluate_suitability`).
Creates NO second risk formula, NO second confidence formula, NO second
suitability formula (Phase 5 task spec §15) — every number here traces to
Phase 2's exact, unmodified code, with exactly the frozen weights:

    wave 0.25, wind 0.15, advisory/hazard 0.20, lightning proxy 0.10,
    restricted distance 0.15, coast distance 0.10, data confidence 0.05

and thresholds (LOW<0.33, MODERATE<0.66, HIGH>=0.66).

**Missing-data policy, deliberately different from Phase 4's routing
provider**: routing needs *some* numeric score per grid cell (A* cannot
leave a cell's cost undefined), so it substitutes a worst-case score.
Orchestration instead returns `status="insufficient_data"` and lets the
Safety Guard (not this agent) decide the consequence via
`has_critical_missing_data` — this agent never pre-empts that decision.
"""
from __future__ import annotations

from app.agents.common.risk_inputs import InsufficientRiskDataError, build_normalized_risk_components
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.risk_suitability.models import RiskSuitabilityResult
from app.models.contracts import AgentResult
from app.risk.config import RiskConfig, get_risk_config
from app.risk.engine import compute_risk
from app.suitability.config import SuitabilityWeights, get_suitability_weights
from app.suitability.engine import evaluate_suitability
from app.suitability.models import PFZReference


class RiskSuitabilityAgent:
    def __init__(
        self,
        *,
        gis_agent: GISGeofencingAgent | None = None,
        risk_config: RiskConfig | None = None,
        suitability_weights: SuitabilityWeights | None = None,
    ):
        self._gis_agent = gis_agent or GISGeofencingAgent()
        self._risk_config = risk_config or get_risk_config()
        self._suitability_weights = suitability_weights or get_suitability_weights()

    def evaluate(
        self,
        *,
        weather: AgentResult,
        marine: AgentResult,
        latitude: float,
        longitude: float,
        distance_to_zone_km: float = 0.0,
        pfz_reference: PFZReference | None = None,
    ) -> RiskSuitabilityResult:
        try:
            components = build_normalized_risk_components(
                weather, marine, latitude=latitude, longitude=longitude, gis_agent=self._gis_agent
            )
        except InsufficientRiskDataError as exc:
            return RiskSuitabilityResult(status="insufficient_data", reason=str(exc))

        risk_result = compute_risk(components, self._risk_config.risk_weights, self._risk_config.risk_thresholds)

        # A conservative combination of two ALREADY-computed Phase 2
        # confidence values (each agent's own `build_agent_result` already
        # applied the exact §22 formula) — the weaker of the two, never a
        # third confidence formula.
        confidence = min(weather.confidence, marine.confidence)

        # architecture.md §21: "Suitability Signal (SST/chlorophyll/PFZ-
        # reference proximity)". No independent SST/chlorophyll-favorability
        # model or real PFZ proximity exists yet (Phase 1 never acquired
        # PFZ data — docs/demo_region.md) — using the inverse of the risk
        # score as a conservative placeholder signal is an HONEST, DOCUMENTED
        # limitation, not a claim of ecological analysis.
        signal_score = 1.0 - risk_result.score

        suitability_result = evaluate_suitability(
            signal_score=signal_score,
            risk_score=risk_result.score,
            distance_to_zone_km=distance_to_zone_km,
            confidence=confidence,
            weights=self._suitability_weights,
            pfz_reference=pfz_reference,
        )

        return RiskSuitabilityResult(
            status="ok", risk_result=risk_result, confidence=confidence, suitability_result=suitability_result
        )
