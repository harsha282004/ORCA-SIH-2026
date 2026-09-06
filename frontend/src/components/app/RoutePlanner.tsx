import { useEffect, useState, type FormEvent } from "react";

import { planRoute, ApiRequestError, type RouteResultData, type ApiErrorDetail, type Coordinate, type RouteComparisonData } from "../../lib/api";
import { ComparisonBarChart } from "../charts/ComparisonBarChart";
import { LineSeriesChart, type ChartSeries } from "../charts/LineSeriesChart";
import { EvidenceList, type EvidenceRow } from "../evidence/Evidence";

// Reference points within the demo coastal region (Mangaluru–Udupi),
// verified as open water against ORCA's own routing test fixtures.
const DEFAULT_ORIGIN = { latitude: 12.8, longitude: 74.2 };
const DEFAULT_DESTINATION = { latitude: 13.3, longitude: 74.1 };

type PlannerState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "result"; routes: RouteResultData[]; comparison: RouteComparisonData | null }
  | { kind: "error"; message: string; detail?: ApiErrorDetail };

interface RoutePlannerProps {
  /** Mirrors the current origin/destination/routes/selection up to a parent
   * (e.g. the Route Planner page's map) — this component still owns all the
   * actual state and API-call logic itself; the callback is purely
   * observational. */
  onStateChange?: (state: {
    origin: Coordinate;
    destination: Coordinate;
    routes: RouteResultData[];
    comparison: RouteComparisonData | null;
    selectedLabel: string | null;
  }) => void;
}

const RISK_BADGE_CLASS: Record<string, string> = {
  LOW: "border-marine-success/40 bg-marine-success/15 text-marine-success",
  MODERATE: "border-marine-warning/40 bg-marine-warning/15 text-marine-warning",
  HIGH: "border-marine-danger/40 bg-marine-danger/15 text-marine-danger",
};

const DECISION_LABEL: Record<string, string> = {
  RECOMMEND: "RECOMMENDED",
  RECOMMEND_WITH_CAUTION: "CAUTION",
  PROVIDE_ALTERNATIVES: "ALTERNATIVES SUGGESTED",
  NO_SAFE_RECOMMENDATION: "BLOCKED",
};

export function RoutePlanner({ onStateChange }: RoutePlannerProps = {}) {
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN);
  const [destination, setDestination] = useState(DEFAULT_DESTINATION);
  const [findAlternatives, setFindAlternatives] = useState(false);
  const [state, setState] = useState<PlannerState>({ kind: "idle" });
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  useEffect(() => {
    const routes = state.kind === "result" ? state.routes : [];
    const comparison = state.kind === "result" ? state.comparison : null;
    onStateChange?.({ origin, destination, routes, comparison, selectedLabel });
    // onStateChange is expected to be a stable identity (or the parent's own
    // concern if not) — including it would re-fire this effect whenever the
    // parent re-renders for unrelated reasons.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origin, destination, state, selectedLabel]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ kind: "loading" });
    setSelectedLabel(null);

    try {
      const response = await planRoute({ origin, destination, max_alternatives: findAlternatives ? 3 : 1 });
      if (response.data) {
        const routes = [response.data, ...(response.alternatives ?? [])];
        setState({ kind: "result", routes, comparison: response.comparison });
        setSelectedLabel(response.comparison?.recommended_label ?? response.data.label);
      } else {
        const detail = response.errors?.[0];
        setState({ kind: "error", message: detail?.message ?? "ORCA could not find a route.", detail });
      }
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "Something went wrong while contacting ORCA.";
      setState({ kind: "error", message });
    }
  };

  const selectedRoute = state.kind === "result" ? state.routes.find((r) => r.label === selectedLabel) : undefined;

  return (
    <div>
      <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2">
        <CoordinateFields label="Origin" value={origin} onChange={setOrigin} />
        <CoordinateFields label="Destination" value={destination} onChange={setDestination} />

        <label className="flex items-center gap-2 text-xs text-marine-white/70 sm:col-span-2">
          <input
            type="checkbox"
            checked={findAlternatives}
            onChange={(e) => setFindAlternatives(e.target.checked)}
            className="h-3.5 w-3.5 accent-marine-cyan"
          />
          Find alternative routes for comparison
        </label>

        <button
          type="submit"
          disabled={state.kind === "loading"}
          className="sm:col-span-2 rounded-full bg-marine-cyan px-5 py-2.5 text-sm font-semibold text-marine-deep transition-colors hover:bg-marine-cyan-light disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state.kind === "loading" ? "Calculating route…" : "Calculate Route"}
        </button>
      </form>

      {state.kind === "loading" && (
        <p className="mt-4 text-sm text-marine-white/60">
          This route is backed by live environmental sampling and can take up to ~15 seconds
          {findAlternatives ? " (alternatives reuse the same sampling, no extra delay)" : ""}.
        </p>
      )}

      {state.kind === "error" && (
        <div className="mt-4 rounded-xl border border-marine-danger/40 bg-marine-danger/10 px-4 py-3 text-sm text-marine-white">
          {state.message}
          {state.detail && <p className="mt-1 text-xs text-marine-white/60">Code: {state.detail.code}</p>}
        </div>
      )}

      {state.kind === "result" && (
        <div className="mt-6 space-y-4">
          {/* --- ROUTE OPTIONS ------------------------------------------- */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-marine-cyan-light">
              Route Option{state.routes.length > 1 ? "s" : ""}
            </h3>
            {state.routes.map((route) => (
              <button
                key={route.label}
                type="button"
                onClick={() => setSelectedLabel(route.label)}
                className={`flex w-full items-center justify-between rounded-xl border px-4 py-2.5 text-left text-sm transition-colors ${
                  route.label === selectedLabel
                    ? "border-marine-cyan bg-marine-cyan/10"
                    : "border-marine-cyan/15 bg-marine-ocean/30 hover:border-marine-cyan/40"
                }`}
              >
                <span className="flex items-center gap-3">
                  <span className="font-semibold text-marine-white">Route {route.label}</span>
                  <span className="text-marine-white/60">{route.metrics.total_distance_km.toFixed(1)} km</span>
                  {state.comparison?.recommended_label === route.label && (
                    <span className="rounded-full border border-marine-cyan/40 bg-marine-cyan/15 px-2 py-0.5 text-[10px] font-semibold text-marine-cyan-light">
                      ORCA PICK
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${RISK_BADGE_CLASS[route.risk_level] ?? ""}`}>
                    {route.risk_level} RISK
                  </span>
                  <span className="text-[10px] font-medium text-marine-white/50">{DECISION_LABEL[route.decision.outcome] ?? route.decision.outcome}</span>
                </span>
              </button>
            ))}
          </div>

          {state.routes.length > 1 && (
            <div className="rounded-xl border border-marine-cyan/15 bg-marine-ocean/30 p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-marine-cyan-light">Route Risk Comparison</p>
              <ComparisonBarChart
                height={140}
                groups={state.routes.map((r) => ({
                  key: r.label,
                  label: `Route ${r.label}`,
                  value: r.metrics.max_risk_score ?? 0,
                  color: r.label === state.comparison?.recommended_label ? "#10B981" : "#38BDF8",
                  sublabel: `${r.metrics.total_distance_km.toFixed(1)} km`,
                }))}
              />
            </div>
          )}

          {state.comparison && (
            <div className="rounded-xl border border-marine-cyan/20 bg-marine-ocean/40 p-3 text-xs leading-relaxed text-marine-white/80">
              <p className="mb-1 font-semibold uppercase tracking-wide text-marine-cyan-light">Comparison</p>
              {state.comparison.reason}
            </div>
          )}

          {/* --- SELECTED ROUTE -------------------------------------------- */}
          {selectedRoute && (
            <div className="space-y-3 rounded-xl border border-marine-cyan/20 bg-marine-ocean/50 p-4 text-sm shadow-sm backdrop-blur">
              <div className="flex flex-wrap gap-2">
                <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${RISK_BADGE_CLASS[selectedRoute.risk_level] ?? ""}`}>
                  {selectedRoute.risk_level} RISK
                </span>
                <span className="rounded-full border border-marine-cyan/30 bg-marine-cyan/10 px-2.5 py-0.5 text-xs font-medium text-marine-cyan-light">
                  {selectedRoute.data_quality === "live" ? "Live environmental data" : "Fixture data"}
                </span>
                <span className="rounded-full border border-marine-white/20 bg-marine-white/5 px-2.5 py-0.5 text-xs font-medium text-marine-white/70">
                  Safety: {selectedRoute.safety.outcome}
                </span>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-marine-white">
                <dt className="text-marine-white/50">Distance</dt>
                <dd>{selectedRoute.metrics.total_distance_km.toFixed(2)} km</dd>
                <dt className="text-marine-white/50">Confidence</dt>
                <dd>{(selectedRoute.confidence * 100).toFixed(0)}%</dd>
                <dt className="text-marine-white/50">Avg. risk score</dt>
                <dd>{selectedRoute.metrics.average_risk_score?.toFixed(3) ?? "—"}</dd>
                <dt className="text-marine-white/50">Max risk score</dt>
                <dd>{selectedRoute.metrics.max_risk_score?.toFixed(3) ?? "—"}</dd>
                <dt className="text-marine-white/50">Hazards near route</dt>
                <dd>
                  {selectedRoute.hazards_near_route.length === 0
                    ? "No relevant hazards detected from available data."
                    : `${selectedRoute.hazards_near_route.length} detected (${selectedRoute.hazards_near_route.map((h) => h.severity).join(", ")})`}
                </dd>
                <dt className="text-marine-white/50">Hazard data source</dt>
                <dd className="capitalize">{selectedRoute.hazard_source_tier}</dd>
              </dl>
              <p className="text-xs italic text-marine-white/50">{selectedRoute.disclaimer}</p>

              {selectedRoute.path_cells.length > 1 && (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-marine-cyan-light">Route Risk Profile</p>
                  <LineSeriesChart
                    height={160}
                    xLabel={(_p, i) => (i % Math.ceil(selectedRoute.path_cells.length / 8) === 0 ? String(i) : "")}
                    tooltipXLabel={(_p, i) => `Cell ${i + 1} of ${selectedRoute.path_cells.length} along route`}
                    xAxisCaption="Route risk profile — real per-cell values, ordered by position along the computed route (not distance-weighted)"
                    series={
                      [
                        {
                          key: "risk",
                          label: "Risk Score",
                          color: "#38BDF8",
                          points: selectedRoute.path_cells.map((c, i) => ({ timestamp: `cell-${i}`, value: c.risk_score })),
                        },
                        {
                          key: "hazard",
                          label: "Hazard Score",
                          color: "#EF4444",
                          points: selectedRoute.path_cells.map((c, i) => ({ timestamp: `cell-${i}`, value: c.hazard_score })),
                        },
                      ] as ChartSeries[]
                    }
                  />
                </div>
              )}

              <EvidenceList
                title="Data & Evidence"
                rows={[
                  { source: "ORCA A* Router + Risk Engine", variable: `Route ${selectedRoute.label} Distance`, value: `${selectedRoute.metrics.total_distance_km.toFixed(1)} km`, confidence: selectedRoute.confidence },
                  { source: "ORCA Risk Engine", variable: "Max Risk Score", value: selectedRoute.metrics.max_risk_score?.toFixed(3) ?? "n/a", confidence: selectedRoute.confidence },
                  ...selectedRoute.hazards_near_route.map(
                    (h): EvidenceRow => ({
                      source: h.source,
                      variable: h.hazard_type.replaceAll("_", " "),
                      value: h.severity,
                      timestamp: h.observed_at,
                      freshness: h.freshness,
                      isAuthoritative: h.is_authoritative,
                      details: h.description,
                    }),
                  ),
                ]}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CoordinateFields({
  label,
  value,
  onChange,
}: {
  label: string;
  value: { latitude: number; longitude: number };
  onChange: (next: { latitude: number; longitude: number }) => void;
}) {
  const idPrefix = label.toLowerCase();
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wide text-marine-white/60">{label}</legend>
      <div className="flex gap-2">
        <div className="flex-1">
          <label htmlFor={`${idPrefix}-lat`} className="sr-only">
            {label} latitude
          </label>
          <input
            id={`${idPrefix}-lat`}
            type="number"
            step="0.01"
            value={value.latitude}
            onChange={(event) => onChange({ ...value, latitude: Number(event.target.value) })}
            className="w-full rounded-lg border border-marine-cyan/25 bg-marine-deep/60 px-3 py-2 text-sm text-marine-white placeholder:text-marine-white/40 focus:border-marine-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
          />
        </div>
        <div className="flex-1">
          <label htmlFor={`${idPrefix}-lon`} className="sr-only">
            {label} longitude
          </label>
          <input
            id={`${idPrefix}-lon`}
            type="number"
            step="0.01"
            value={value.longitude}
            onChange={(event) => onChange({ ...value, longitude: Number(event.target.value) })}
            className="w-full rounded-lg border border-marine-cyan/25 bg-marine-deep/60 px-3 py-2 text-sm text-marine-white placeholder:text-marine-white/40 focus:border-marine-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
          />
        </div>
      </div>
    </fieldset>
  );
}
