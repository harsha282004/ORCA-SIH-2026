// Typed client for ORCA's real backend endpoints (backend/app/api/v1/*.py).
// No fake/mock responses live here — every function calls the actual
// FastAPI service; failures are surfaced as thrown errors for callers to
// render honestly, never silently replaced with placeholder data.
import { API_BASE_URL } from "../config";

export type DependencyStatus = "healthy" | "unhealthy";

export interface ReadinessResponse {
  status: "ready" | "not_ready";
  dependencies: {
    database: DependencyStatus;
    postgis: DependencyStatus;
    redis: DependencyStatus;
  };
}

// --- POST /api/v1/query — backend/app/api/v1/query.py ------------------

export type SafetyGuardOutcome = "PASS" | "BLOCK_BOUNDARY" | "BLOCK_MISSING_DATA" | "BLOCK_LOW_CONFIDENCE" | "BLOCK_HAZARD";
export type DecisionOutcome = "RECOMMEND" | "RECOMMEND_WITH_CAUTION" | "PROVIDE_ALTERNATIVES" | "NO_SAFE_RECOMMENDATION";

export interface Decision {
  outcome: DecisionOutcome;
  risk_level: "LOW" | "MODERATE" | "HIGH";
  risk_score: number;
  confidence: number;
  safety_guard_outcome: SafetyGuardOutcome;
  reason: string;
  alternative_used: boolean;
}

export interface SafetyGuardResult {
  outcome: SafetyGuardOutcome;
  reason: string;
  triggered_rule: string;
}

// --- Marine Safety & Hazard Intelligence — Phase 4, backend/app/hazard/* -
//
// `Hazard` mirrors backend/app/hazard/models.py's `Hazard` verbatim. Every
// hazard here is either a real cyclone (GDACS, an aggregator of the actual
// issuing regional authority) or a real wave/wind reading crossing the
// EXISTING Risk Engine's own saturation thresholds — never LLM-invented,
// never a fabricated point.

export type HazardType = "CYCLONE" | "HIGH_WIND" | "HIGH_WAVES" | "THUNDERSTORM_PROXY" | "GEOFENCE_BOUNDARY";
export type HazardSeverity = "INFO" | "ADVISORY" | "WARNING" | "DANGER" | "CRITICAL";
export type MarineSafetyLevel = "SAFE" | "CAUTION" | "WARNING" | "DANGER" | "UNKNOWN";
export type HazardFreshness = "CURRENT" | "FORECAST" | "STALE" | "UNKNOWN";
export type HazardSourceAvailability = "AVAILABLE" | "LIMITED" | "UNAVAILABLE";

export interface Hazard {
  hazard_type: HazardType;
  severity: HazardSeverity;
  title: string;
  description: string;
  latitude?: number | null;
  longitude?: number | null;
  distance_km?: number | null;
  valid_from?: string | null;
  valid_until?: string | null;
  observed_at?: string | null;
  source: string;
  is_authoritative: boolean;
  is_proxy: boolean;
  freshness: HazardFreshness;
  confidence?: number | null;
}

export interface HazardSourceStatus {
  hazard_type: HazardType;
  source: string;
  is_authoritative: boolean;
  programmatically_accessible: boolean;
  status: HazardSourceAvailability;
  reason: string;
}

export interface MarineSafetyStatus {
  level: MarineSafetyLevel;
  reason: string;
  decision_outcome?: DecisionOutcome | null;
  safety_guard_outcome?: SafetyGuardOutcome | null;
  risk_level?: string | null;
  risk_score?: number | null;
  confidence?: number | null;
  hazards: Hazard[];
  unavailable_sources: HazardSourceStatus[];
  generated_at: string;
}

export interface ClarificationNeeded {
  reason: string;
  missing_fields: string[];
  original_query: string;
}

export interface QueryResponseData {
  status: "completed" | "clarification_needed";
  language?: string;
  decision?: Decision | null;
  safety?: SafetyGuardResult | null;
  explanation?: string | null;
  used_fallback_template?: boolean | null;
  route_note?: string | null;
  clarification?: ClarificationNeeded;
  // Phase 4 — real hazard-awareness surfaced for EVERY conversational
  // intent via the shared `safety_guard` orchestration node (see
  // backend/app/api/v1/query.py). Never LLM-invented.
  marine_safety?: MarineSafetyStatus | null;
  // Phase 5 — present only when a route_planning query named a resolvable
  // destination and the LangGraph `route` node actually computed a real
  // route (backend/app/orchestration/nodes.py::OrchestrationNodes.route).
  route?: RouteResultData | null;
  route_alternatives?: RouteResultData[];
  route_comparison?: RouteComparisonData | null;
  // Phase 3 — present only when app.api.v1.query's zone_recommendation
  // path (backend/app/api/v1/query.py::_handle_zone_recommendation) ran.
  // Phase 6: the same shape, minus the sample-generation fields, is also
  // used by a "which is safest?" follow-up answered from already-computed
  // candidates (app.api.v1.query::_handle_conversational_followup) — those
  // fields are optional here for exactly that reason.
  fishing_candidates?: {
    top?: Record<string, unknown>;
    ranked: Record<string, unknown>[];
    ranked_count?: number;
    avoid_count?: number;
    sample_count?: number;
    requested_time?: string;
    method?: string;
  } | null;
  // Phase 6 (task §17) — true only on a response answered by reusing an
  // already-computed structured result (a route alternative, a route/
  // fishing comparison) rather than a fresh deterministic evaluation.
  reused_prior_result?: boolean;
  // Phase 7 (task §4/§18/§25) — present only for a WHAT-IF scenario query
  // (backend/app/api/v1/query.py::_handle_scenario_query). `null` means
  // ORCA recognized a scenario attempt but it was underspecified (no
  // supported variable/explicit number) — the `explanation` field then
  // carries the clarification text.
  scenario?: ScenarioQueryData | null;
  // Phase 7 (task §8/§9/§10) — present only for a time-window/best-time
  // query (backend/app/api/v1/query.py::_handle_temporal_window_query).
  temporal?: TemporalQueryData | null;
}

export interface ScenarioQueryData {
  label: string; // "SIMULATION — NOT LIVE DATA"
  variable: "wave_height" | "wind_speed";
  unit: string;
  baseline_value: number;
  scenario_value: number;
  delta: number;
  assumption: string;
  scope_note?: string | null;
  baseline: { risk_suitability: Record<string, unknown>; safety: SafetyGuardResult; decision: Decision };
  scenario_result: { risk_suitability: Record<string, unknown>; safety: SafetyGuardResult; decision: Decision };
  risk_score_delta: number;
  decision_changed: boolean;
  safety_outcome_changed: boolean;
}

export interface TemporalSeriesEntry {
  timestamp: string;
  status: "ranked" | "avoid" | "insufficient_data";
  risk_score?: number | null;
  risk_level?: "LOW" | "MODERATE" | "HIGH" | null;
  suitability_score?: number | null;
  suitability_category?: string | null;
  decision_outcome?: DecisionOutcome | null;
  safety_outcome?: SafetyGuardOutcome | null;
  environmental_context?: { wave_height_m?: number | null; wind_speed_ms?: number | null; sea_surface_temperature_c?: number | null } | null;
  reason?: string | null;
}

export interface TemporalQueryData {
  series: TemporalSeriesEntry[];
  best_time_index: number | null;
  hours_evaluated: number;
  ranking?: string;
  limitations?: string[];
}

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export interface QueryApiResponse {
  data: QueryResponseData | null;
  evidence: Record<string, unknown>[] | null;
  confidence: number | null;
  provenance: Record<string, unknown> | null;
  errors: ApiErrorDetail[] | null;
  session_id: string;
  query_id: string;
}

// Phase 6 (task §4) — the three reliably-tested languages; matches
// backend/app/i18n/languages.py::SUPPORTED_LANGUAGES exactly.
export type SupportedLanguage = "en" | "hi" | "kn";
export const SUPPORTED_LANGUAGES: { code: SupportedLanguage; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "kn", label: "ಕನ್ನಡ" },
];

export interface AskOrcaRequest {
  query: string;
  session_id?: string;
  // Phase 6 (task §32) — omit/undefined for automatic detection (the
  // default everywhere). When set, overrides the RESPONSE language only —
  // never intent/entity extraction or any deterministic calculation (see
  // backend/app/api/v1/query.py::QueryAPIRequest.language_override's own
  // docstring).
  language_override?: SupportedLanguage;
}

// --- POST /api/v1/route — backend/app/api/v1/route.py -------------------

export interface Coordinate {
  latitude: number;
  longitude: number;
}

export interface RouteMetrics {
  total_distance_km: number;
  total_cost: number;
  cell_count: number;
  average_risk_score: number | null;
  max_risk_score: number | null;
  // Phase 5 — always 0.0 for a plain single-route request; nonzero only on
  // a generated alternative (backend/app/routing/costs.py's 5th cost term).
  alternative_penalty_cost?: number;
}

// backend/app/routing/models.py's RouteCellRef — one grid cell along the
// reconstructed path, carrying the SAME per-cell risk_score the Risk
// Engine attached to it (app.agents.environmental_provider); never
// recomputed on the frontend.
export interface RouteCellRef {
  cell_id: string;
  row: number;
  col: number;
  latitude: number;
  longitude: number;
  risk_score: number | null;
  hazard_score: number | null;
  geofence_soft_penalty: number;
}

export interface RouteResultData {
  route_id: string;
  origin: Coordinate;
  destination: Coordinate;
  // backend/app/routing/models.py's RouteResult.path_coordinates — the
  // actual computed route geometry. Present in every real response; this
  // interface previously omitted it (nothing had needed it before a real
  // map existed to draw it on).
  path_coordinates: Coordinate[];
  path_cells: RouteCellRef[];
  metrics: RouteMetrics;
  feasibility_status: "FEASIBLE";
  mode: "live" | "demo";
  data_quality: "fixture" | "live";
  confidence: number;
  disclaimer: string;
  // Phase 4 §19/20 — real cyclone hazards within relevance range of the
  // ALREADY-computed path (backend/app/hazard/route_hazards.py). Always
  // present, even when empty. Wave/wind hazards are not duplicated here —
  // they are already priced into the route's own cost function.
  hazards_near_route: Hazard[];
  hazard_source_tier: "live" | "cached" | "unavailable";
  // Phase 5 (task §9/§11) — a deterministic route-level classification,
  // reusing the EXISTING Risk/Safety Guard/Decision Engine
  // (backend/app/routing/safety.py). Present on every route (primary and
  // every alternative) with the exact same shape.
  label: string; // "A" (primary/optimal), "B", "C" for alternatives — presentation order only, no ranking meaning by itself
  risk_level: "LOW" | "MODERATE" | "HIGH";
  safety: SafetyGuardResult;
  decision: Decision;
}

export interface RouteApiResponse {
  data: RouteResultData | null;
  confidence: number | null;
  errors: ApiErrorDetail[] | null;
  // Phase 5 (task §12/§14) — always present (possibly `[]`/`null`), never a
  // shape-shifting response: a caller reading only `data`/`confidence`/
  // `errors` is unaffected by this extension.
  alternatives: RouteResultData[] | null;
  comparison: RouteComparisonData | null;
}

export interface RouteComparisonData {
  recommended_label: string | null;
  reason: string;
  generated_at: string;
}

export interface RouteRequestBody {
  origin: Coordinate;
  destination: Coordinate;
  requested_time?: string;
  // Phase 5 (task §12) — 1 (default) is the exact pre-Phase-5 behavior;
  // 2-5 additionally requests deterministic, graph-derived alternatives
  // (backend/app/routing/alternatives.py) — bounded, never "hundreds of routes."
  max_alternatives?: number;
}

class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function postJson<TResponse>(path: string, body: unknown): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiRequestError("ORCA's backend is not reachable right now. Please try again shortly.");
  }

  let parsed: TResponse;
  try {
    parsed = (await response.json()) as TResponse;
  } catch {
    throw new ApiRequestError(`ORCA's backend returned an unreadable response (HTTP ${response.status}).`, response.status);
  }

  return parsed;
}

export async function getReadiness(): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/ready`);
  return (await response.json()) as ReadinessResponse;
}

export async function askOrca(request: AskOrcaRequest): Promise<QueryApiResponse> {
  return postJson<QueryApiResponse>("/api/v1/query", request);
}

export async function planRoute(request: RouteRequestBody): Promise<RouteApiResponse> {
  return postJson<RouteApiResponse>("/api/v1/route", request);
}

// --- GET /api/v1/layers/* — backend/app/api/v1/layers.py ------------------
//
// Every layer endpoint is a thin, read-only serialization of an EXISTING
// deterministic ORCA engine (GIS geofencing, the Risk Engine, the Fishing
// Suitability Engine) or a real live Weather/Oceanographic sample — never
// computed here. This client never calculates risk, suitability, geofence
// membership, or a route; it only fetches and renders what the backend
// already decided.

export type FreshnessStatus = "CURRENT" | "FORECAST" | "CACHED" | "STALE" | "STATIC" | "UNAVAILABLE";

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: Record<string, unknown>;
    geometry: { type: string; coordinates: unknown };
  }>;
}

export interface LayerErrorDetail {
  code: string;
  message: string;
}

export interface LayerApiResponse<TMeta = Record<string, unknown>> {
  data: GeoJsonFeatureCollection | null;
  meta: TMeta | null;
  errors: LayerErrorDetail[] | null;
}

async function getJson<TResponse>(path: string, params?: Record<string, string | undefined>): Promise<TResponse> {
  const query = params
    ? Object.entries(params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v as string)}`)
        .join("&")
    : "";
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}${query ? `?${query}` : ""}`);
  } catch {
    throw new ApiRequestError("ORCA's backend is not reachable right now. Please try again shortly.");
  }
  try {
    return (await response.json()) as TResponse;
  } catch {
    throw new ApiRequestError(`ORCA's backend returned an unreadable response (HTTP ${response.status}).`, response.status);
  }
}

export interface GeofencesLayerMeta {
  layer: "geofences";
  classification: "static";
  status: FreshnessStatus;
  is_authoritative: boolean;
  source_tier: string;
  source: string;
  disclaimer: string;
  count: number;
  generated_at: string;
}

export interface BathymetryLayerMeta {
  layer: "bathymetry";
  classification: "static";
  status: FreshnessStatus;
  available: boolean;
  source: string | null;
  source_url?: string;
  dataset_version?: string;
  acquisition_status?: string | null;
  is_authoritative: boolean | null;
  acquired_at?: string;
  sample_count?: number;
  depth_range_m?: { min: number | null; max: number | null };
  depth_convention?: string;
  reason?: string;
  generated_at: string;
}

export interface RiskSurfaceLayerMeta {
  layer: "risk-surface";
  classification: "derived";
  status: FreshnessStatus;
  data_quality: "fixture" | "live";
  confidence: number;
  temporal_validity_status: string;
  resolution_km: number;
  cell_count: number;
  requested_time: string;
  generated_at: string;
  source: string;
  risk_thresholds: { low_max: number; moderate_max: number };
}

export interface OceanographyLayerMeta {
  layer: "oceanography";
  classification: "dynamic";
  source: string;
  sample_count: number;
  requested_time: string;
  generated_at: string;
  chlorophyll: { available: false; reason: string };
}

// Phase 2, Part A1 — real INCOIS SST, acquired in Phase 1, now wired into
// this SAME existing oceanography response (backend/app/api/v1/layers.py's
// `_incois_sst_block`) rather than a duplicate endpoint. Kept as its own
// top-level block — a different provider, a different (sparse, acquired)
// representation, never merged into the live Open-Meteo `data` above.
export interface IncoisSstLayerMeta {
  layer: "incois-sst";
  classification: "dynamic";
  status: FreshnessStatus;
  available: boolean;
  source: string;
  source_url?: string;
  is_authoritative?: boolean;
  acquired_at?: string;
  unit?: string;
  sample_count?: number;
  value_range?: { min: number | null; max: number | null };
  temporal_semantics?: string;
  note?: string;
  reason?: string;
  generated_at: string;
}

export interface OceanographyApiResponse extends LayerApiResponse<OceanographyLayerMeta> {
  incois_sst: LayerApiResponse<IncoisSstLayerMeta>;
}

export interface SuitabilityLayerMeta {
  layer: "suitability";
  classification: "derived";
  source: string;
  pfz_status: "unavailable" | "available";
  sample_count: number;
  requested_time: string;
  generated_at: string;
}

export interface ChlorophyllLayerMeta {
  layer: "chlorophyll";
  classification: "dynamic";
  status: FreshnessStatus;
  available: boolean;
  source: string;
  source_url?: string;
  is_authoritative?: boolean;
  acquired_at?: string;
  unit?: string;
  sample_count?: number;
  value_range?: { min: number | null; max: number | null };
  temporal_semantics?: string;
  reason?: string;
  generated_at: string;
}

export async function getGeofencesLayer(): Promise<LayerApiResponse<GeofencesLayerMeta>> {
  return getJson("/api/v1/layers/geofences");
}

export async function getBathymetryLayer(): Promise<LayerApiResponse<BathymetryLayerMeta>> {
  return getJson("/api/v1/layers/bathymetry");
}

export async function getRiskSurfaceLayer(options?: { at?: string }): Promise<LayerApiResponse<RiskSurfaceLayerMeta>> {
  return getJson("/api/v1/layers/risk-surface", { at: options?.at });
}

export async function getOceanographyLayer(options?: { at?: string }): Promise<OceanographyApiResponse> {
  return getJson("/api/v1/layers/oceanography", { at: options?.at });
}

export async function getSuitabilityLayer(options?: { at?: string }): Promise<LayerApiResponse<SuitabilityLayerMeta>> {
  return getJson("/api/v1/layers/suitability", { at: options?.at });
}

export async function getChlorophyllLayer(): Promise<LayerApiResponse<ChlorophyllLayerMeta>> {
  return getJson("/api/v1/layers/chlorophyll");
}

// --- GET /api/v1/layers/marine-timeseries ----------------------------------
//
// Phase 1 built this endpoint; Phase 2 is the first to actually call it
// from the frontend, for the real time slider — every requested timestamp
// below is Open-Meteo's own genuine forecast value for that hour, never a
// label change over the same data.

export interface MarineTimeseriesPoint {
  timestamp: string;
  values: Record<string, number | null>;
  units: Record<string, string>;
}

export interface MarineTimeseriesMeta {
  layer: "marine-timeseries";
  classification: "dynamic";
  source: string;
  variables: string[];
  timestamp_count: number;
  temporal_resolution: string;
  is_forecast: boolean;
  retrieved_at: string;
  generated_at: string;
}

export interface MarineTimeseriesApiResponse {
  data: { latitude: number; longitude: number; series: MarineTimeseriesPoint[] } | null;
  meta: MarineTimeseriesMeta | null;
  errors: LayerErrorDetail[] | null;
}

export async function getMarineTimeseries(latitude: number, longitude: number): Promise<MarineTimeseriesApiResponse> {
  return getJson("/api/v1/layers/marine-timeseries", { latitude: String(latitude), longitude: String(longitude) });
}

// --- GET/POST /api/v1/fishing/* — backend/app/api/v1/fishing.py -----------
//
// Phase 3 (Fishing Intelligence). Every candidate below is produced by
// `app.fishing.engine`, which composes the SAME deterministic Risk Engine,
// Suitability Engine, Safety Guard, and Decision Engine every other ORCA
// surface already uses — this client never ranks, scores, or filters
// anything itself.

export type CandidateStatus = "ranked" | "avoid" | "insufficient_data";
export type SuitabilityCategory = "HIGH" | "MODERATE" | "LOW" | "NOT_RECOMMENDED";

export interface EnvironmentalContext {
  sea_surface_temperature_c?: number | null;
  wave_height_m?: number | null;
  wave_direction_deg?: number | null;
  wind_speed_ms?: number | null;
  ocean_current_velocity_ms?: number | null;
}

export interface FishingCandidateProps {
  status: CandidateStatus;
  reason?: string | null;
  suitability_score?: number | null;
  suitability_category?: SuitabilityCategory | null;
  suitability_signal_is_risk_proxy: boolean;
  risk_score?: number | null;
  risk_level?: "LOW" | "MODERATE" | "HIGH" | null;
  risk_factors: Array<{ name: string; normalized_value: number; weight: number; contribution: number }>;
  safety_outcome?: SafetyGuardOutcome | null;
  decision_outcome?: DecisionOutcome | null;
  is_authoritative_restricted?: boolean | null;
  confidence?: number | null;
  environmental_context?: EnvironmentalContext | null;
  // Phase 4 — real hazards considered for this candidate
  // (backend/app/fishing/engine.py's optional hazard-awareness).
  // `active_hazards_checked` disambiguates "not evaluated" (hazard
  // detection wasn't requested for this call) from "evaluated, clear."
  active_hazards: Hazard[];
  active_hazards_checked: boolean;
  distance_km?: number | null;
  rank?: number | null;
  source: string;
  timestamp: string;
}

export interface FishingCandidatesMeta {
  layer: "fishing-candidates";
  classification: "derived";
  method: string;
  sample_count: number;
  ranked_count: number;
  avoid_count: number;
  requested_time: string;
  generated_at: string;
  source: string;
  pfz_status: string;
}

export async function getFishingCandidates(options?: { at?: string; minSuitability?: number; maxRisk?: number }): Promise<LayerApiResponse<FishingCandidatesMeta>> {
  return getJson("/api/v1/fishing/candidates", {
    at: options?.at,
    min_suitability: options?.minSuitability?.toString(),
    max_risk: options?.maxRisk?.toString(),
  });
}

export interface NearestFishingResponse {
  data: { type: "Feature"; properties: FishingCandidateProps; geometry: { type: "Point"; coordinates: [number, number] } } | null;
  meta: Record<string, unknown> | null;
  errors: LayerErrorDetail[] | null;
}

export async function getNearestFishingArea(latitude: number, longitude: number): Promise<NearestFishingResponse> {
  return getJson("/api/v1/fishing/nearest", { latitude: String(latitude), longitude: String(longitude) });
}

export interface CompareFishingResponse {
  data: { candidates: (FishingCandidateProps & { latitude: number; longitude: number })[]; better_candidate_index: number | null; reason: string } | null;
  meta: Record<string, unknown> | null;
  errors: LayerErrorDetail[] | null;
}

export async function compareFishingAreas(points: Coordinate[]): Promise<CompareFishingResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/fishing/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points }),
    });
  } catch {
    throw new ApiRequestError("ORCA's backend is not reachable right now. Please try again shortly.");
  }
  return (await response.json()) as CompareFishingResponse;
}

export interface TemporalFishingResponse {
  data: { latitude: number; longitude: number; series: (FishingCandidateProps & { latitude: number; longitude: number })[]; recommended_index: number | null } | null;
  meta: Record<string, unknown> | null;
  errors: LayerErrorDetail[] | null;
}

export async function getTemporalFishingSuitability(latitude: number, longitude: number, hours = 6): Promise<TemporalFishingResponse> {
  return getJson("/api/v1/fishing/temporal", { latitude: String(latitude), longitude: String(longitude), hours: String(hours) });
}

// --- GET /api/v1/safety/* — backend/app/api/v1/safety.py -------------------
//
// Phase 4 (Marine Safety & Hazard Intelligence). Every field below is
// produced by the EXISTING deterministic Risk/Suitability/Safety/Decision
// pipeline plus `app.hazard.engine` — this client never classifies safety,
// never decides hazard severity, never invents a hazard.

export interface SafetyStatusMeta {
  latitude: number;
  longitude: number;
  weather_source_tier: string;
  marine_source_tier: string;
  requested_time: string;
  generated_at: string;
  source: string;
}

export interface SafetyStatusApiResponse {
  data: MarineSafetyStatus | null;
  meta: SafetyStatusMeta | null;
  errors: LayerErrorDetail[] | null;
}

export async function getSafetyStatus(latitude: number, longitude: number, at?: string): Promise<SafetyStatusApiResponse> {
  return getJson("/api/v1/safety/status", { latitude: String(latitude), longitude: String(longitude), at });
}

export interface SafetyHazardsMeta {
  latitude: number;
  longitude: number;
  hazard_count: number;
  unavailable_sources: HazardSourceStatus[];
  requested_time: string;
  generated_at: string;
  source: string;
}

// Matches the same `LayerApiResponse<TMeta>` shape every other
// `GET /api/v1/layers/*`-style endpoint uses (a plain GeoJSON
// FeatureCollection with `Record<string, unknown>` properties) so this
// composes directly with `useMapLayer`/`buildHazardsLayer`/`EvidencePanel`
// exactly like every other map layer — properties are cast to `Hazard`'s
// shape at the point of use (see mapLayers.ts/EvidencePanel.tsx), not here.
export async function getSafetyHazards(latitude: number, longitude: number, at?: string): Promise<LayerApiResponse<SafetyHazardsMeta>> {
  return getJson("/api/v1/safety/hazards", { latitude: String(latitude), longitude: String(longitude), at });
}

export interface SafetySourcesApiResponse {
  data: { sources: HazardSourceStatus[] } | null;
  meta: { generated_at: string } | null;
  errors: LayerErrorDetail[] | null;
}

export async function getSafetySources(): Promise<SafetySourcesApiResponse> {
  return getJson("/api/v1/safety/sources");
}

// --- GET /api/v1/safety/temporal — Phase 7 ---------------------------------
//
// Reuses the exact same real per-hour series `GET /api/v1/fishing/temporal`
// already returns (app.fishing.temporal.evaluate_temporal_suitability),
// re-framed around the safety question and ranked by lowest real risk
// score among hours that already passed the Safety Guard/Decision Engine.

export interface SafetyTemporalMeta {
  hours_evaluated: number;
  temporal_resolution: string;
  is_forecast: boolean;
  ranking: string;
  limitations: string[];
  generated_at: string;
  source: string;
}

export interface SafetyTemporalApiResponse {
  data: { latitude: number; longitude: number; series: (FishingCandidateProps & { latitude: number; longitude: number })[]; best_time_index: number | null } | null;
  meta: SafetyTemporalMeta | null;
  errors: LayerErrorDetail[] | null;
}

export async function getTemporalSafety(latitude: number, longitude: number, hours = 6): Promise<SafetyTemporalApiResponse> {
  return getJson("/api/v1/safety/temporal", { latitude: String(latitude), longitude: String(longitude), hours: String(hours) });
}

// --- POST /api/v1/scenario — backend/app/api/v1/scenario.py (Phase 7) ------
//
// "What if wave height became 3.5m?" — a deterministic perturbation of the
// session's own real, already-fetched baseline (never a fresh fetch, never
// an invented value). Requires an existing session_id from a prior
// POST /api/v1/query call.

export interface ScenarioRequestBody {
  session_id: string;
  wave_height_delta_m?: number;
  wind_speed_delta_ms?: number;
  wave_height_target_m?: number;
  wind_speed_target_ms?: number;
  language?: SupportedLanguage;
}

export interface ScenarioSnapshotData {
  risk_suitability: Record<string, unknown>;
  safety: SafetyGuardResult;
  decision: Decision;
}

export interface ScenarioResultData {
  label: string;
  perturbation: { wave_height_delta_m: number | null; wind_speed_delta_ms: number | null };
  baseline: ScenarioSnapshotData;
  scenario: ScenarioSnapshotData;
  risk_score_delta: number;
  decision_changed: boolean;
  safety_outcome_changed: boolean;
}

export interface ScenarioApiResponse {
  data: ScenarioResultData | null;
  explanation: string | null;
  used_fallback_template: boolean | null;
  errors: ApiErrorDetail[] | null;
}

export async function postScenario(request: ScenarioRequestBody): Promise<ScenarioApiResponse> {
  return postJson<ScenarioApiResponse>("/api/v1/scenario", request);
}

export { ApiRequestError };
