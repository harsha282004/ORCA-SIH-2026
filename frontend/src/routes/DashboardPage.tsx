import { useCallback, useEffect, useMemo, useState } from "react";
import { Anchor, Compass, RefreshCw, ShieldAlert, ShieldCheck, ShieldQuestion, TriangleAlert, Waves } from "lucide-react";

import { RouteMap } from "../components/map/RouteMap";
import { LayerControlPanel, type LayerGroup } from "../components/map/LayerControlPanel";
import { MapLegend, type MapLegendSectionKey } from "../components/map/MapLegend";
import { EvidencePanel } from "../components/map/EvidencePanel";
import { LineSeriesChart, type ChartSeries } from "../components/charts/LineSeriesChart";
import { EvidenceList, type EvidenceRow } from "../components/evidence/Evidence";
import { ThunderstormCard } from "../components/hazards/HazardIntelCards";
import { ButtonLink, Button } from "../components/ui/Button";
import { useMarineLayers } from "../hooks/useMarineLayers";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import {
  getNearestFishingArea,
  getSafetyStatus,
  getTemporalSafety,
  planRoute,
  type FishingCandidateProps,
  type MarineSafetyLevel,
  type MarineSafetyStatus,
  type RouteResultData,
  type SafetyTemporalApiResponse,
} from "../lib/api";

// Phase 2 — a slightly wider real window than the original 6h default so
// genuine (small) real hour-to-hour movement has more room to show; still
// exactly what GET /api/v1/safety/temporal's own real Open-Meteo-backed
// series returns for however many forecast hours it actually has (never
// padded/looped to force a full 12).
const TEMPORAL_WINDOW_HOURS = 12;

// The same demo-region reference point already used by MarineMapPage/
// SafetyPage (backend/app/config.py's DEMO_BBOX centroid) — one canonical
// "where am I looking" point across the whole app, never a page-specific
// invention. The route origin mirrors RoutePlannerPage's own default
// (a Mangaluru-area port coordinate), so "Recommended Route" below asks the
// SAME real A* engine the dedicated Route Planner uses.
const REGION_CENTER = { latitude: 13.075, longitude: 74.275 };
const REGION_LABEL = "Mangaluru–Udupi Coastal Region";
const PORT_ORIGIN = { latitude: 12.8, longitude: 74.2 };

type FetchState<T> = { kind: "loading" } | { kind: "loaded"; value: T } | { kind: "error"; message: string };

const SAFETY_STYLE: Record<MarineSafetyLevel, { text: string; bg: string; icon: typeof ShieldCheck; label: string }> = {
  SAFE: { text: "text-marine-success", bg: "border-marine-success/40 bg-marine-success/15", icon: ShieldCheck, label: "Safe" },
  CAUTION: { text: "text-marine-blue", bg: "border-marine-blue/40 bg-marine-mist", icon: TriangleAlert, label: "Caution" },
  WARNING: { text: "text-marine-warning", bg: "border-marine-warning/40 bg-marine-warning/15", icon: TriangleAlert, label: "Warning" },
  DANGER: { text: "text-marine-danger", bg: "border-marine-danger/40 bg-marine-danger/15", icon: ShieldAlert, label: "Danger" },
  // UNKNOWN must never read as SAFE (task §34) — distinct neutral styling, never green.
  UNKNOWN: { text: "text-marine-ink-muted", bg: "border-marine-border bg-marine-surface-alt", icon: ShieldQuestion, label: "Unknown" },
};

function ConditionTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-marine-border bg-marine-surface px-4 py-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold text-marine-ink">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-marine-ink-muted">{sub}</p>}
    </div>
  );
}

function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="animate-pulse rounded-2xl border border-marine-border bg-marine-surface p-4">
      <div className="h-3 w-1/3 rounded bg-marine-border" />
      <div className="mt-4 space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} className="h-3 rounded bg-marine-border" style={{ width: `${80 - i * 15}%` }} />
        ))}
      </div>
    </div>
  );
}

/**
 * Phase 8 — /dashboard: a real marine-operations overview built entirely
 * from data ORCA's deterministic engines already compute, reusing the
 * SAME endpoints and map machinery every other page uses
 * (getNearestFishingArea / getSafetyStatus / getTemporalSafety / planRoute,
 * RouteMap + useMarineLayers). No new backend endpoint was needed — see
 * docs/PHASE_8_EVIDENCE_CHARTS_DASHBOARD_REPORT.md §3.
 */
export function DashboardPage() {
  const reducedMotion = usePrefersReducedMotion();

  const [conditions, setConditions] = useState<FetchState<FishingCandidateProps>>({ kind: "loading" });
  const [safety, setSafety] = useState<FetchState<MarineSafetyStatus>>({ kind: "loading" });
  const [temporal, setTemporal] = useState<FetchState<SafetyTemporalApiResponse["data"]>>({ kind: "loading" });
  const [route, setRoute] = useState<{ kind: "idle" | "loading" | "loaded" | "error"; data?: RouteResultData; alternatives?: RouteResultData[]; message?: string }>({ kind: "idle" });

  const marine = useMarineLayers({ risk: true, waves: true });

  const loadAll = useCallback(() => {
    setConditions({ kind: "loading" });
    setSafety({ kind: "loading" });
    setTemporal({ kind: "loading" });

    getNearestFishingArea(REGION_CENTER.latitude, REGION_CENTER.longitude)
      .then((r) => {
        if (r.errors?.length) return setConditions({ kind: "error", message: r.errors[0].message });
        if (!r.data) return setConditions({ kind: "error", message: "No current conditions available for this location." });
        setConditions({ kind: "loaded", value: r.data.properties });
      })
      .catch(() => setConditions({ kind: "error", message: "ORCA's backend is not reachable right now." }));

    getSafetyStatus(REGION_CENTER.latitude, REGION_CENTER.longitude)
      .then((r) => {
        if (r.errors?.length) return setSafety({ kind: "error", message: r.errors[0].message });
        if (!r.data) return setSafety({ kind: "error", message: "Marine safety status is not available." });
        setSafety({ kind: "loaded", value: r.data });
      })
      .catch(() => setSafety({ kind: "error", message: "ORCA's backend is not reachable right now." }));

    getTemporalSafety(REGION_CENTER.latitude, REGION_CENTER.longitude, TEMPORAL_WINDOW_HOURS)
      .then((r) => {
        if (r.errors?.length) return setTemporal({ kind: "error", message: r.errors[0].message });
        setTemporal({ kind: "loaded", value: r.data });
      })
      .catch(() => setTemporal({ kind: "error", message: "ORCA's backend is not reachable right now." }));
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const allFailed = conditions.kind === "error" && safety.kind === "error" && temporal.kind === "error";

  const level: MarineSafetyLevel = safety.kind === "loaded" ? safety.value.level : "UNKNOWN";
  const LevelIcon = SAFETY_STYLE[level].icon;

  const loadRoute = () => {
    const destination = conditions.kind === "loaded" ? { latitude: REGION_CENTER.latitude, longitude: REGION_CENTER.longitude } : REGION_CENTER;
    setRoute({ kind: "loading" });
    planRoute({ origin: PORT_ORIGIN, destination, max_alternatives: 2 })
      .then((r) => {
        if (r.errors?.length || !r.data) return setRoute({ kind: "error", message: r.errors?.[0]?.message ?? "No route could be computed." });
        setRoute({ kind: "loaded", data: r.data, alternatives: r.alternatives ?? [] });
      })
      .catch(() => setRoute({ kind: "error", message: "ORCA's backend is not reachable right now." }));
  };

  // Real per-hour wave/wind series (task §9A/§21) — straight from the SAME
  // backend series the temporal fishing/safety panels already use, never a
  // second fetch or a client-side reconstruction.
  const temporalChartSeries: ChartSeries[] = useMemo(() => {
    if (temporal.kind !== "loaded" || !temporal.value) return [];
    const series = temporal.value.series;
    return [
      { key: "wave", label: "Wave Height", color: "#38BDF8", unit: "m", points: series.map((s) => ({ timestamp: s.timestamp, value: s.environmental_context?.wave_height_m ?? null })) },
      { key: "wind", label: "Wind Speed", color: "#F59E0B", unit: "m/s", points: series.map((s) => ({ timestamp: s.timestamp, value: s.environmental_context?.wind_speed_ms ?? null })) },
    ];
  }, [temporal]);

  const activeLegendLayers: MapLegendSectionKey[] = [
    ...(marine.enabled.risk ? (["risk"] as const) : []),
    ...(marine.enabled.waves || marine.enabled.wind || marine.enabled.sst || marine.enabled.currents ? (["marine"] as const) : []),
    ...(marine.enabled.suitability ? (["fishing"] as const) : []),
    ...(marine.enabled.geofences ? (["safety"] as const) : []),
    ...(marine.enabled.bathymetry || marine.enabled.chlorophyll ? (["reference"] as const) : []),
  ];

  const layerGroups: LayerGroup[] = [
    {
      title: "Conditions",
      layers: [
        { key: "waves", label: "Waves", available: true },
        { key: "wind", label: "Wind", available: true },
        { key: "sst", label: "SST", available: true },
        { key: "currents", label: "Currents", available: true },
      ],
    },
    {
      title: "ORCA Intelligence",
      layers: [
        { key: "risk", label: "Risk", available: true },
        { key: "suitability", label: "Fishing Suitability", available: true },
        { key: "geofences", label: "Geofences", available: true },
      ],
    },
    { title: "Reference", layers: [{ key: "bathymetry", label: "Bathymetry", available: true }, { key: "chlorophyll", label: "Chlorophyll-a", available: true }] },
  ];

  const evidenceRows: EvidenceRow[] = useMemo(() => {
    const rows: EvidenceRow[] = [];
    if (conditions.kind === "loaded") {
      const c = conditions.value;
      rows.push({
        source: "ORCA Fishing Suitability Engine",
        variable: "Fishing Suitability",
        value: c.suitability_score != null ? `${Math.round(c.suitability_score * 100)}/100 — ${c.suitability_category ?? "n/a"}` : "n/a",
        timestamp: c.timestamp,
        confidence: c.confidence,
        details: "ORCA's own deterministic suitability score — not fish detection, not a guaranteed catch.",
      });
      if (c.environmental_context?.wave_height_m != null) {
        rows.push({ source: c.source, variable: "Wave Height", value: `${c.environmental_context.wave_height_m.toFixed(2)} m`, timestamp: c.timestamp, freshness: "FORECAST" });
      }
      if (c.environmental_context?.wind_speed_ms != null) {
        rows.push({ source: c.source, variable: "Wind Speed", value: `${c.environmental_context.wind_speed_ms.toFixed(2)} m/s`, timestamp: c.timestamp, freshness: "FORECAST" });
      }
      if (c.environmental_context?.sea_surface_temperature_c != null) {
        rows.push({ source: c.source, variable: "Sea Surface Temperature", value: `${c.environmental_context.sea_surface_temperature_c.toFixed(1)} °C`, timestamp: c.timestamp, coverage: "Partial regional sample", freshness: "FORECAST" });
      }
    }
    if (safety.kind === "loaded") {
      rows.push({
        source: "ORCA Risk Engine + Safety Guard",
        variable: "Marine Safety Level",
        value: safety.value.level,
        timestamp: safety.value.generated_at,
        confidence: safety.value.confidence,
      });
      for (const h of safety.value.hazards) {
        rows.push({
          source: h.source,
          variable: h.hazard_type.replaceAll("_", " "),
          value: h.severity,
          timestamp: h.observed_at,
          freshness: h.freshness,
          isAuthoritative: h.is_authoritative,
          details: h.description,
        });
      }
      for (const u of safety.value.unavailable_sources) {
        rows.push({ source: u.source, variable: u.hazard_type.replaceAll("_", " "), value: "UNAVAILABLE", freshness: "UNAVAILABLE", details: u.reason });
      }
    }
    if (temporal.kind === "loaded" && temporal.value) {
      rows.push({
        source: "Open-Meteo (via ORCA temporal engine)",
        variable: "Temporal Forecast Window",
        value: `${temporal.value.series.length} real hourly points`,
        coverage: "Point-based hourly temporal data",
        details: "Hourly wave/wind forecast — never a smoothed or extrapolated series.",
      });
    }
    return rows;
  }, [conditions, safety, temporal]);

  return (
    <main className="min-h-screen bg-marine-surface-alt pt-20">
      <div className="mx-auto max-w-7xl px-6 py-10 sm:px-10 lg:px-16 lg:py-14">
        {allFailed ? (
          <div className="flex flex-col items-center gap-4 rounded-2xl border border-marine-danger/40 bg-marine-danger/10 py-16 text-center">
            <ShieldAlert className="text-marine-danger" size={32} />
            <p className="text-sm font-semibold uppercase tracking-wide text-marine-danger">ORCA Data Connection Lost</p>
            <Button variant="danger" size="md" onClick={loadAll}>
              Retry
            </Button>
          </div>
        ) : (
          <div className="orca-dashboard-grid">
            {/* --- HEADER --------------------------------------------------- */}
            <div className="orca-dashboard-area-header flex flex-wrap items-end justify-between gap-4 pb-2">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">Marine Intelligence</p>
                <h1 className="mt-2 text-3xl font-semibold tracking-tight text-marine-ink sm:text-4xl">{REGION_LABEL}</h1>
                <p className="mt-1.5 text-sm text-marine-ink-muted">
                  {safety.kind === "loaded" ? `Updated ${new Date(safety.value.generated_at).toLocaleString()}` : "Updating…"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-semibold uppercase tracking-wide ${SAFETY_STYLE[level].bg} ${SAFETY_STYLE[level].text}`}>
                  <LevelIcon size={15} /> {level}
                </span>
                <Button variant="secondary" size="md" onClick={loadAll}>
                  <RefreshCw size={14} /> Refresh
                </Button>
              </div>
            </div>

            {/* --- CURRENT CONDITIONS ---------------------------------------- */}
            <section className="orca-dashboard-area-current">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-marine-blue">Current Conditions</h2>
              {conditions.kind === "loading" ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <SkeletonCard key={i} lines={1} />
                  ))}
                </div>
              ) : conditions.kind === "error" ? (
                <p className="text-sm text-marine-danger">{conditions.message}</p>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  <ConditionTile label="Wave" value={conditions.value.environmental_context?.wave_height_m != null ? `${conditions.value.environmental_context.wave_height_m.toFixed(1)} m` : "n/a"} sub="Forecast" />
                  <ConditionTile label="Wind" value={conditions.value.environmental_context?.wind_speed_ms != null ? `${conditions.value.environmental_context.wind_speed_ms.toFixed(1)} m/s` : "n/a"} sub="Forecast" />
                  <ConditionTile label="SST" value={conditions.value.environmental_context?.sea_surface_temperature_c != null ? `${conditions.value.environmental_context.sea_surface_temperature_c.toFixed(1)} °C` : "n/a"} sub="Partial sample" />
                  <ConditionTile
                    label="Current"
                    value={conditions.value.environmental_context?.ocean_current_velocity_ms != null ? `${conditions.value.environmental_context.ocean_current_velocity_ms.toFixed(2)} m/s` : "n/a"}
                    sub="Forecast"
                  />
                  <ConditionTile label="Safety" value={SAFETY_STYLE[level].label} sub={safety.kind === "loaded" ? safety.value.risk_level ?? undefined : undefined} />
                </div>
              )}
            </section>

            {/* --- MAP --------------------------------------------------------
                Phase 1 fix: the map used to look "overlapped" because both
                floating panels (Map Layers, top-left; Legend, bottom-right)
                defaulted to fully expanded, growing tall enough to cover a
                large share of the map and, on other pages using the same
                panels, collide with each other. Both now default collapsed
                (see LayerControlPanel/DataStatusPanel), and the map itself
                is taller and sits in its own clearly bordered container,
                never sharing space with the Safety panel (a separate grid
                cell, task §1's "details must never overlap the map"). */}
            <section className="orca-dashboard-area-map relative h-[70vh] min-h-[560px] overflow-hidden rounded-2xl border border-marine-border">
              <RouteMap origin={REGION_CENTER} destination={REGION_CENTER} routeCoordinates={null} reducedMotion={reducedMotion} className="h-full w-full" deckLayers={marine.deckLayers} />
              <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-3">
                <LayerControlPanel groups={layerGroups} enabled={marine.enabled} onToggle={(k) => marine.toggleLayer(k as never)} onRefresh={marine.refresh} refreshing={marine.refreshing} />
              </div>
              <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col items-end gap-3">
                <MapLegend only={activeLegendLayers.length > 0 ? activeLegendLayers : undefined} />
              </div>
              {marine.selected && (
                <div className="pointer-events-none absolute right-3 top-3">
                  <EvidencePanel feature={marine.selected} onClose={() => marine.setSelected(null)} />
                </div>
              )}
              <div className="pointer-events-none absolute bottom-3 left-3">
                <ButtonLink to="/marine-map" variant="secondary" size="sm" className="pointer-events-auto bg-marine-surface/95">
                  Open full Marine Map →
                </ButtonLink>
              </div>
            </section>

            {/* --- SAFETY ------------------------------------------------------ */}
            <section className="orca-dashboard-area-safety flex flex-col gap-4 rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Marine Safety</h2>
              {safety.kind === "loading" && <SkeletonCard />}
              {safety.kind === "error" && <p className="text-sm text-marine-danger">{safety.message}</p>}
              {safety.kind === "loaded" && (
                <>
                  <div className={`flex items-center gap-2.5 text-2xl font-semibold ${SAFETY_STYLE[level].text}`}>
                    <LevelIcon size={24} />
                    {SAFETY_STYLE[level].label}
                  </div>
                  <p className="text-sm leading-relaxed text-marine-ink-muted">{safety.value.reason}</p>
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">Active Hazards</p>
                    {safety.value.hazards.length === 0 ? (
                      <p className="text-sm text-marine-success">No active verified hazards.</p>
                    ) : (
                      <ul className="space-y-2">
                        {safety.value.hazards.map((h, i) => (
                          <li key={i} className="flex items-center justify-between rounded-lg border border-marine-border bg-marine-surface-alt px-3 py-2 text-sm text-marine-ink">
                            <span>{h.title}</span>
                            <span className="font-semibold text-marine-warning">{h.severity}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {safety.value.unavailable_sources.length > 0 && (
                      <p className="mt-2 text-xs italic text-marine-ink-muted">
                        Hazard data unavailable: {safety.value.unavailable_sources.map((u) => u.hazard_type).join(", ")}.
                      </p>
                    )}
                  </div>
                  <ButtonLink to="/safety" variant="secondary" size="sm" className="mt-1 w-fit">
                    Open Marine Safety →
                  </ButtonLink>
                </>
              )}
            </section>

            {/* --- TEMPORAL -------------------------------------------------
                Phase 2: this chart plots the SAME real per-hour Open-Meteo
                series /safety/temporal returns everywhere else in the app —
                never a hand-tuned curve. If real wave height barely moves
                over the window (it currently does not — see the Source/
                Updated block below), the line is genuinely, honestly flat;
                see docs report §2 for the live values checked before this
                redesign. */}
            <section className="orca-dashboard-area-temporal rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-6">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Marine Conditions — Temporal</h2>
                {temporal.kind === "loaded" && temporal.value && (
                  <span className="text-xs text-marine-ink-muted">Real hourly Open-Meteo forecast — never smoothed or extrapolated.</span>
                )}
              </div>
              {temporal.kind === "loading" ? (
                <SkeletonCard lines={4} />
              ) : temporal.kind === "error" ? (
                <p className="text-sm text-marine-danger">{temporal.message}</p>
              ) : (
                <>
                  {conditions.kind === "loaded" && conditions.value.environmental_context?.wave_height_m != null && (
                    <div className="mb-4 flex flex-wrap items-end justify-between gap-4 border-b border-marine-border pb-4">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">Wave Height</p>
                        <p className="mt-1 text-3xl font-semibold text-marine-ink">{conditions.value.environmental_context.wave_height_m.toFixed(2)} m</p>
                        <span className="mt-1 inline-block rounded-full border border-marine-cyan/40 bg-marine-cyan/15 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-marine-blue">
                          Forecast
                        </span>
                      </div>
                      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-marine-ink-muted">
                        <dt className="text-marine-ink-muted">Source</dt>
                        <dd>Open-Meteo Marine</dd>
                        <dt className="text-marine-ink-muted">Data Type</dt>
                        <dd>Forecast (hourly)</dd>
                        <dt className="text-marine-ink-muted">Updated</dt>
                        <dd>{new Date(conditions.value.timestamp).toLocaleString()}</dd>
                      </dl>
                    </div>
                  )}
                  <LineSeriesChart series={temporalChartSeries} highlightIndex={temporal.value?.best_time_index ?? null} />
                </>
              )}
            </section>

            {/* --- FISHING INTELLIGENCE --------------------------------------- */}
            <section className="orca-dashboard-area-fishing flex flex-col gap-4 rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-6">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-marine-blue">
                <Waves size={15} /> Fishing Intelligence
              </h2>
              {conditions.kind === "loading" && <SkeletonCard />}
              {conditions.kind === "error" && <p className="text-sm text-marine-danger">{conditions.message}</p>}
              {conditions.kind === "loaded" && (
                <>
                  <div className="flex items-baseline gap-3">
                    <span className="text-5xl font-bold text-marine-ink">{conditions.value.suitability_score != null ? Math.round(conditions.value.suitability_score * 100) : "—"}</span>
                    <span className="text-base text-marine-ink-muted">/ 100</span>
                  </div>
                  <span className="w-fit rounded-full border border-marine-cyan/40 bg-marine-cyan/15 px-3 py-1 text-sm font-semibold uppercase tracking-wide text-marine-blue">
                    {conditions.value.suitability_category ?? "n/a"}
                  </span>
                  {temporal.kind === "loaded" && temporal.value?.best_time_index != null && (
                    <p className="text-sm text-marine-ink-muted">
                      <span className="text-marine-ink-muted">Best window:</span>{" "}
                      <span className="font-semibold text-marine-ink">
                        {new Date(temporal.value.series[temporal.value.best_time_index].timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </p>
                  )}
                  {conditions.value.risk_factors.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">Key Factors</p>
                      <ul className="space-y-1.5 text-sm text-marine-ink-muted">
                        {conditions.value.risk_factors.slice(0, 3).map((f) => (
                          <li key={f.name} className="flex justify-between border-b border-marine-border pb-1.5 last:border-0">
                            <span className="capitalize">{f.name.replaceAll("_", " ")}</span>
                            <span className="font-mono text-marine-ink">{f.contribution.toFixed(3)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="text-xs italic text-marine-ink-muted">Not fish abundance, not PFZ detection — a decision-support score only.</p>
                  <ButtonLink to="/fishing" variant="secondary" size="sm" className="w-fit">
                    Open Fishing Intelligence →
                  </ButtonLink>
                </>
              )}
            </section>

            {/* --- ROUTE INTELLIGENCE ------------------------------------------ */}
            <section className="orca-dashboard-area-route flex flex-col gap-4 rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-6">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-marine-blue">
                <Compass size={15} /> Route Intelligence
              </h2>
              {route.kind === "idle" && (
                <>
                  <p className="text-sm text-marine-ink-muted">Calculate a real risk-weighted route from the demo port to this region.</p>
                  <Button variant="secondary" size="sm" onClick={loadRoute} className="w-fit">
                    Calculate Recommended Route
                  </Button>
                </>
              )}
              {route.kind === "loading" && <SkeletonCard lines={2} />}
              {route.kind === "error" && <p className="text-sm text-marine-danger">{route.message}</p>}
              {route.kind === "loaded" && route.data && (
                <>
                  <dl className="grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-marine-border bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Distance</dt>
                      <dd className="mt-1 text-lg font-semibold text-marine-ink">{route.data.metrics.total_distance_km.toFixed(1)} km</dd>
                    </div>
                    <div className="rounded-xl border border-marine-border bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Risk</dt>
                      <dd className="mt-1 text-lg font-semibold text-marine-ink">{route.data.risk_level}</dd>
                    </div>
                    <div className="rounded-xl border border-marine-border bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Safety</dt>
                      <dd className="mt-1 text-lg font-semibold text-marine-ink">{route.data.safety.outcome}</dd>
                    </div>
                    <div className="rounded-xl border border-marine-border bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Alternatives</dt>
                      <dd className="mt-1 text-lg font-semibold text-marine-ink">{route.alternatives?.length ?? 0}</dd>
                    </div>
                  </dl>
                  <div className="flex items-center gap-1.5 text-sm text-marine-ink-muted">
                    <Anchor size={13} /> Hazards near route: {route.data.hazards_near_route.length}
                  </div>
                </>
              )}
              <ButtonLink to="/route-planner" variant="secondary" size="sm" className="w-fit">
                View Route Planner →
              </ButtonLink>
            </section>

            {/* --- DATA & EVIDENCE ------------------------------------------- */}
            <div className="orca-dashboard-area-evidence flex flex-col gap-6">
              {safety.kind === "loaded" && <ThunderstormCard hazards={safety.value.hazards} />}
              <EvidenceList title="Data & Evidence" rows={evidenceRows} />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
