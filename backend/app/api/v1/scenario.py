"""Scenario Engine endpoint — architecture.md §32, §34 (`POST /scenario`).

    "Perturb a prior query's baseline, return diffed result"

The baseline is the prior turn's already-resolved intent + weather/marine
snapshot from Session State (`app.session.models.SessionState`) — this
endpoint never fetches fresh environmental data and never invents a
baseline. If no prior turn exists yet (or it never completed with weather/
marine data), that is a controlled `SCENARIO_BASELINE_UNAVAILABLE` error,
never a guess (architecture.md's no-fabrication rule).

Phase 7 additions (task §17/§21/§30/§31/§43), all additive — the
underlying `app.scenario.engine.run_scenario`/`app.scenario.models
.ScenarioPerturbation` are UNCHANGED, still the one deterministic
perturb-then-re-score engine:

- Absolute TARGET values ("wave height becomes 3.5 m") alongside the
  existing DELTA fields — this endpoint computes `target - real_baseline`
  before constructing the same `ScenarioPerturbation`, so the deterministic
  engine itself only ever sees a delta, exactly as before.
- A real Groq explanation (`EvidenceExplanationAgent`, reused unchanged),
  gated behind the SAME grounding/fallback contract every other explained
  response already uses — never a dependency for the deterministic result
  itself (task §43: a Groq failure still returns the full scenario data).
- The existing Temporal Validity Gate is checked on the baseline snapshot
  before any scenario is computed (task §31) — a stale/expired baseline
  refuses rather than silently scoring stale data as if it were current.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ValidationError

from app.agents.evidence_explanation.agent import EvidenceExplanationAgent
from app.agents.gis.agent import GISGeofencingAgent
from app.agents.risk_suitability.agent import RiskSuitabilityAgent
from app.api.v1.query import get_session_store
from app.i18n.languages import is_supported
from app.provenance.models import DecisionProvenanceGraph, RiskProvenance, ScenarioProvenance, SuitabilityProvenance
from app.risk.config import get_risk_config
from app.scenario.engine import run_scenario
from app.scenario.models import ScenarioPerturbation, ScenarioResult
from app.session.store import SessionStore

router = APIRouter()


def get_gis_agent() -> GISGeofencingAgent:
    return GISGeofencingAgent()


def get_risk_suitability_agent() -> RiskSuitabilityAgent:
    return RiskSuitabilityAgent()


def get_evidence_agent() -> EvidenceExplanationAgent:
    # A real dependency-injection seam (not a bare `EvidenceExplanationAgent()`
    # construction inline) specifically so offline tests can override it with
    # a `FakeLLMProvider`-backed instance — the same pattern the rest of the
    # API layer already uses for the GIS/Risk agents above. A hardcoded
    # construction here would silently make every offline test that reaches
    # a successful scenario a REAL Groq call — caught and fixed within this
    # same phase (tests/api/test_scenario.py now overrides this).
    return EvidenceExplanationAgent()


class ScenarioAPIRequest(BaseModel):
    session_id: str
    wave_height_delta_m: float | None = None
    wind_speed_delta_ms: float | None = None
    # Phase 7 — the ABSOLUTE value the user named ("becomes 3.5 m"), as
    # opposed to the pre-existing delta fields above ("+1 m"). Exactly one
    # of {delta, target} may be given per variable — never both, an
    # ambiguous request the endpoint rejects rather than silently picking one.
    wave_height_target_m: float | None = None
    wind_speed_target_ms: float | None = None
    # None (default) = the session's own last detected/used language —
    # never a second language-detection pass (Phase 6 infrastructure reused).
    language: str | None = None


class ScenarioErrorResponse(BaseModel):
    code: str
    message: str


class ScenarioAPIResponse(BaseModel):
    data: dict | None = None
    explanation: str | None = None
    used_fallback_template: bool | None = None
    errors: list[ScenarioErrorResponse] | None = None


_VARIABLE_UNITS = {"wave_height_m": "m", "wind_speed_ms": "m/s"}


def _resolve_delta(*, delta: float | None, target: float | None, baseline_value: float | None, field_name: str) -> tuple[float | None, str | None]:
    """Returns (delta, error_message). Never both a delta AND a target for
    the same variable (ambiguous — task §32's "do not silently convert
    invalid input"). A target requires a real baseline value to diff
    against; if the baseline snapshot doesn't carry this variable at all,
    that is reported, never silently treated as 0.
    """
    if delta is not None and target is not None:
        return None, f"{field_name}: specify either a delta or a target value, not both"
    if target is not None:
        if baseline_value is None:
            return None, f"{field_name}: no real baseline value is available to compute a scenario delta against"
        return target - baseline_value, None
    return delta, None


@router.post("/scenario")
def create_scenario(
    request: ScenarioAPIRequest,
    response: Response,
    session_store: SessionStore = Depends(get_session_store),
    gis_agent: GISGeofencingAgent = Depends(get_gis_agent),
    risk_suitability_agent: RiskSuitabilityAgent = Depends(get_risk_suitability_agent),
    evidence_agent: EvidenceExplanationAgent = Depends(get_evidence_agent),
) -> ScenarioAPIResponse:
    session = session_store.get(request.session_id)
    if session is None:
        response.status_code = 404
        return ScenarioAPIResponse(
            errors=[ScenarioErrorResponse(code="SESSION_NOT_FOUND", message=f"no session {request.session_id!r} found")]
        )

    if session.last_intent is None or session.last_weather_snapshot is None or session.last_marine_snapshot is None:
        response.status_code = 422
        return ScenarioAPIResponse(
            errors=[
                ScenarioErrorResponse(
                    code="SCENARIO_BASELINE_UNAVAILABLE",
                    message="this session has no completed prior query to build a scenario from — "
                    "call POST /api/v1/query with this session_id first",
                )
            ]
        )

    # Phase 7 (task §31): the Temporal Validity Gate's own verdict on the
    # baseline snapshot, already computed when it was originally fetched —
    # reused here as a gate, never recomputed with a second formula.
    if session.last_weather_snapshot.temporal_validity_status in ("STALE", "EXPIRED") or session.last_marine_snapshot.temporal_validity_status in ("STALE", "EXPIRED"):
        response.status_code = 422
        return ScenarioAPIResponse(
            errors=[
                ScenarioErrorResponse(
                    code="SCENARIO_BASELINE_STALE",
                    message="Scenario assessment unavailable because the underlying marine data is stale.",
                )
            ]
        )

    baseline_wave = session.last_marine_snapshot.data.get("wave_height") if session.last_marine_snapshot.status != "failed" else None
    baseline_wind = session.last_weather_snapshot.data.get("wind_speed_10m") if session.last_weather_snapshot.status != "failed" else None

    wave_delta, wave_error = _resolve_delta(
        delta=request.wave_height_delta_m, target=request.wave_height_target_m, baseline_value=baseline_wave, field_name="wave_height"
    )
    wind_delta, wind_error = _resolve_delta(
        delta=request.wind_speed_delta_ms, target=request.wind_speed_target_ms, baseline_value=baseline_wind, field_name="wind_speed"
    )
    if wave_error or wind_error:
        response.status_code = 422
        return ScenarioAPIResponse(
            errors=[ScenarioErrorResponse(code="INVALID_PERTURBATION", message=" ; ".join(m for m in (wave_error, wind_error) if m))]
        )

    try:
        perturbation = ScenarioPerturbation(wave_height_delta_m=wave_delta, wind_speed_delta_ms=wind_delta)
    except ValidationError as exc:
        response.status_code = 422
        return ScenarioAPIResponse(errors=[ScenarioErrorResponse(code="INVALID_PERTURBATION", message=str(exc))])

    result: ScenarioResult = run_scenario(
        intent=session.last_intent,
        weather=session.last_weather_snapshot,
        marine=session.last_marine_snapshot,
        perturbation=perturbation,
        risk_suitability_agent=risk_suitability_agent,
        gis_agent=gis_agent,
        risk_config=get_risk_config(),
    )

    language = request.language if request.language and is_supported(request.language) else session.last_language
    explanation_text, used_fallback = _explain_scenario(
        result=result, baseline_wave=baseline_wave, baseline_wind=baseline_wind, language=language,
        persona=session.last_intent.persona, evidence_agent=evidence_agent,
    )

    data = result.model_dump(mode="json")
    return ScenarioAPIResponse(data=data, explanation=explanation_text, used_fallback_template=used_fallback)


def _explain_scenario(
    *, result: ScenarioResult, baseline_wave: float | None, baseline_wind: float | None, language: str, persona: str,
    evidence_agent: EvidenceExplanationAgent,
) -> tuple[str | None, bool | None]:
    """One Groq call (task §44 — never more than one explanation call per
    scenario), gated so a Groq failure never blocks the deterministic
    result itself (task §43) — this function's caller always has `result`
    (already computed) regardless of what happens here.
    """
    perturbation = result.perturbation
    if perturbation.wave_height_delta_m is not None and baseline_wave is not None:
        variable, unit = "wave_height_m", _VARIABLE_UNITS["wave_height_m"]
        baseline_value = baseline_wave
        scenario_value = baseline_wave + perturbation.wave_height_delta_m
    elif perturbation.wind_speed_delta_ms is not None and baseline_wind is not None:
        variable, unit = "wind_speed_ms", _VARIABLE_UNITS["wind_speed_ms"]
        baseline_value = baseline_wind
        scenario_value = baseline_wind + perturbation.wind_speed_delta_ms
    else:
        return None, None

    br = result.baseline.risk_suitability.risk_result
    sr = result.scenario.risk_suitability.risk_result
    provenance = DecisionProvenanceGraph(
        query_id="scenario",
        risk=RiskProvenance(factors=sr.factors if sr else [], score=sr.score if sr else 0.0, level=sr.level if sr else "HIGH"),
        scenario=ScenarioProvenance(
            variable=variable, unit=unit, baseline_value=baseline_value, scenario_value=scenario_value,
            baseline_risk_score=br.score if br else 0.0, scenario_risk_score=sr.score if sr else 0.0,
            baseline_decision_outcome=result.baseline.decision.outcome, scenario_decision_outcome=result.scenario.decision.outcome,
        ),
        safety=result.scenario.safety,
        decision=result.scenario.decision,
        generated_at=datetime.now(timezone.utc),
    )
    try:
        explanation = evidence_agent.explain(provenance=provenance, language=language, persona=persona)
    except Exception:  # noqa: BLE001 — task §43: LLM failure must never block the deterministic scenario result
        return None, None
    return explanation.rationale, explanation.used_fallback_template
