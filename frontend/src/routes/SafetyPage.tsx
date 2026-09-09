import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion, TriangleAlert } from "lucide-react";

import { RouteMap } from "../components/map/RouteMap";
import { MapLegend } from "../components/map/MapLegend";
import { EvidencePanel } from "../components/map/EvidencePanel";
import { DataStatusPanel, type StatusRow } from "../components/map/DataStatusPanel";
import { buildGeofenceLayer, buildHazardsLayer, type SelectedFeature } from "../components/map/mapLayers";
import { LineSeriesChart, type ChartSeries } from "../components/charts/LineSeriesChart";
import { EvidenceList, type EvidenceRow } from "../components/evidence/Evidence";
import { CycloneCard, ThunderstormCard } from "../components/hazards/HazardIntelCards";
import { Button } from "../components/ui/Button";
import { useMapLayer } from "../hooks/useMapLayer";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import {
  getGeofencesLayer,
  getSafetyHazards,
  getSafetySources,
  getSafetyStatus,
  getTemporalSafety,
  type Hazard,
  type HazardSourceStatus,
  type MarineSafetyLevel,
  type MarineSafetyStatus,
  type SafetyHazardsMeta,
  type SafetyTemporalApiResponse,
} from "../lib/api";

const REGION_CENTER = { latitude: 13.075, longitude: 74.275 };

const LEVEL_STYLE: Record<MarineSafetyLevel, { bg: string; text: string; icon: typeof ShieldCheck; label: string }> = {
  SAFE: { bg: "bg-marine-success/15 border-marine-success/40", text: "text-marine-success", icon: ShieldCheck, label: "Safe" },
  CAUTION: { bg: "bg-marine-mist border-marine-blue/40", text: "text-marine-blue", icon: TriangleAlert, label: "Caution" },
  WARNING: { bg: "bg-marine-warning/15 border-marine-warning/40", text: "text-marine-warning", icon: TriangleAlert, label: "Warning" },
  DANGER: { bg: "bg-marine-danger/15 border-marine-danger/40", text: "text-marine-danger", icon: ShieldAlert, label: "Danger" },
  UNKNOWN: { bg: "bg-marine-surface-alt border-marine-border", text: "text-marine-ink-muted", icon: ShieldQuestion, label: "Unknown / Limited" },
};

const HAZARD_SEVERITY_TEXT: Record<string, string> = {
  INFO: "text-marine-ink-muted",
  ADVISORY: "text-[#92600A]",
  WARNING: "text-marine-warning",
  DANGER: "text-marine-danger",
  CRITICAL: "text-[#9D174D]",
};

/**
 * Marine Safety & Hazard Intelligence page (Phase 4) — CURRENT SAFETY
 * STATUS / ACTIVE HAZARDS / MAP / SELECTED HAZARD / SAFETY FACTORS /
 * RECOMMENDATION / DATA AVAILABILITY, per the task's own mockup. Every
 * value shown here comes straight from `GET /api/v1/safety/*`
 * (backend/app/api/v1/safety.py), itself a composition of the EXISTING
 * deterministic Risk/Suitability/Safety Guard/Decision engines plus the new
 * `app.hazard.engine` — this page computes nothing itself.
 */
export function SafetyPage() {
  const reducedMotion = usePrefersReducedMotion();
  const [location, setLocation] = useState(REGION_CENTER);
  const [latInput, setLatInput] = useState(String(REGION_CENTER.latitude));
  const [lonInput, setLonInput] = useState(String(REGION_CENTER.longitude));
  const [selected, setSelected] = useState<SelectedFeature | null>(null);

  const [status, setStatus] = useState<{ kind: "loading" | "loaded" | "error"; data?: MarineSafetyStatus; message?: string }>({ kind: "loading" });
  const [sources, setSources] = useState<HazardSourceStatus[] | null>(null);
  // Phase 7 (task §12/§35) — real per-hour safety window, fetched on demand.
  const [temporal, setTemporal] = useState<{ kind: "idle" | "loading" | "loaded"; data?: SafetyTemporalApiResponse["data"]; meta?: SafetyTemporalApiResponse["meta"] }>({ kind: "idle" });

  const hazards = useMapLayer<SafetyHazardsMeta>(true, () => getSafetyHazards(location.latitude, location.longitude));
  const geofences = useMapLayer(true, getGeofencesLayer);

  const loadStatus = useCallback((lat: number, lon: number) => {
    setStatus({ kind: "loading" });
    getSafetyStatus(lat, lon)
      .then((response) => {
        if (response.errors && response.errors.length > 0) {
          setStatus({ kind: "error", message: response.errors[0].message });
        } else if (response.data) {
          setStatus({ kind: "loaded", data: response.data });
        } else {
          setStatus({ kind: "error", message: "Marine safety status is not available for this location." });
        }
      })
      .catch(() => setStatus({ kind: "error", message: "ORCA's backend is not reachable right now." }));
  }, []);

  useEffect(() => {
    loadStatus(location.latitude, location.longitude);
  }, [location, loadStatus]);

  // `useMapLayer` only auto-fetches once (on first enable); a location
  // change after that must explicitly trigger a re-fetch with the NEW
  // coordinates — done here (after the `location` state has actually
  // updated, so the fetcher closure sees it) rather than inside the form
  // submit handler, where it would still capture the stale, pre-update
  // location. Skips the very first render, where `useMapLayer`'s own
  // mount-time auto-fetch already covers the initial location.
  const hazardsRefresh = hazards.refresh;
  const isFirstLocationRender = useRef(true);
  useEffect(() => {
    if (isFirstLocationRender.current) {
      isFirstLocationRender.current = false;
      return;
    }
    hazardsRefresh();
  }, [location, hazardsRefresh]);

  useEffect(() => {
    getSafetySources()
      .then((r) => setSources(r.data?.sources ?? null))
      .catch(() => setSources(null));
  }, []);

  const loadTemporal = async () => {
    setTemporal({ kind: "loading" });
    const response = await getTemporalSafety(location.latitude, location.longitude, 6);
    setTemporal({ kind: "loaded", data: response.data, meta: response.meta ?? undefined });
  };

  const handleCheck = (e: React.FormEvent) => {
    e.preventDefault();
    const lat = Number(latInput);
    const lon = Number(lonInput);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    setLocation({ latitude: lat, longitude: lon });
    setTemporal({ kind: "idle" });
  };

  const deckLayers = [];
  if (geofences.state.kind === "loaded") deckLayers.push(buildGeofenceLayer(geofences.state.data, setSelected));
  if (hazards.state.kind === "loaded") deckLayers.push(buildHazardsLayer(hazards.state.data, setSelected));

  const level = status.kind === "loaded" ? status.data!.level : "UNKNOWN";
  const LevelIcon = LEVEL_STYLE[level].icon;

  const activeHazards: Hazard[] = status.kind === "loaded" ? status.data!.hazards : [];
  const unavailable: HazardSourceStatus[] = status.kind === "loaded" ? status.data!.unavailable_sources : [];

  const statusRows: StatusRow[] = [
    { label: "Hazards", state: hazards.state, sampleNote: hazards.state.kind === "loaded" ? `${hazards.state.meta.hazard_count} detected` : undefined },
    { label: "Geofences", state: geofences.state },
  ];

  return (
    <main className="min-h-screen bg-marine-surface-alt pt-20">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-10 sm:px-10 lg:px-16 lg:py-14">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">Deterministic Safety Intelligence</p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-marine-ink sm:text-4xl">Marine Safety.</h1>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-marine-ink-muted">
            A combined marine safety status, derived entirely from ORCA's existing deterministic Risk Engine, Safety Guard, and Decision
            Engine, plus real detected hazards (active cyclones via GDACS, and wave/wind readings at the Risk Engine's own saturation
            thresholds). ORCA never converts missing hazard data into "safe" — a source that could not be checked is always disclosed below.
            For what-if scenarios ("would it still be safe if wind increased to 15 m/s?"), ask{" "}
            <a href="/ask-orca" className="text-marine-blue underline hover:text-marine-cyan">
              Ask ORCA
            </a>
            .
          </p>
        </div>

        <form onSubmit={handleCheck} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col text-xs text-marine-ink-muted">
            Latitude
            <input
              type="number"
              step="0.01"
              value={latInput}
              onChange={(e) => setLatInput(e.target.value)}
              className="mt-1 w-32 rounded-lg border border-marine-cyan/25 bg-marine-surface px-3 py-2 text-sm text-marine-ink focus:border-marine-cyan focus:outline-none"
            />
          </label>
          <label className="flex flex-col text-xs text-marine-ink-muted">
            Longitude
            <input
              type="number"
              step="0.01"
              value={lonInput}
              onChange={(e) => setLonInput(e.target.value)}
              className="mt-1 w-32 rounded-lg border border-marine-cyan/25 bg-marine-surface px-3 py-2 text-sm text-marine-ink focus:border-marine-cyan focus:outline-none"
            />
          </label>
          <Button type="submit">Check Safety</Button>
        </form>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_400px]">
          <div className="flex flex-col gap-6">
            {/* --- CURRENT SAFETY STATUS ------------------------------------ */}
            <section className={`rounded-2xl border p-6 ${LEVEL_STYLE[level].bg}`}>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-ink-muted">Current Safety Status</h2>
              {status.kind === "loading" && <p className="mt-3 text-sm text-marine-ink-muted">Evaluating…</p>}
              {status.kind === "error" && <p className="mt-3 text-sm text-marine-danger">{status.message}</p>}
              {status.kind === "loaded" && (
                <>
                  <div className={`mt-3 flex items-center gap-3 text-4xl font-bold ${LEVEL_STYLE[level].text}`}>
                    <LevelIcon size={36} />
                    {LEVEL_STYLE[level].label}
                  </div>
                  <p className="mt-3 text-base leading-relaxed text-marine-ink-muted">{status.data!.reason}</p>
                  <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div className="rounded-xl bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Decision</dt>
                      <dd className="mt-1 text-sm font-semibold text-marine-ink">{status.data!.decision_outcome ?? "n/a"}</dd>
                    </div>
                    <div className="rounded-xl bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Safety guard</dt>
                      <dd className="mt-1 text-sm font-semibold text-marine-ink">{status.data!.safety_guard_outcome ?? "n/a"}</dd>
                    </div>
                    <div className="rounded-xl bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Risk</dt>
                      <dd className="mt-1 text-sm font-semibold text-marine-ink">
                        {status.data!.risk_level ?? "n/a"} ({status.data!.risk_score?.toFixed(3) ?? "n/a"})
                      </dd>
                    </div>
                    <div className="rounded-xl bg-marine-surface-alt p-3">
                      <dt className="text-xs text-marine-ink-muted">Confidence</dt>
                      <dd className="mt-1 text-sm font-semibold text-marine-ink">{status.data!.confidence != null ? `${(status.data!.confidence * 100).toFixed(0)}%` : "n/a"}</dd>
                    </div>
                  </dl>
                </>
              )}
            </section>

            {/* --- TEMPORAL SAFETY WINDOW (Phase 7) --------------------------- */}
            <section className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-6">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Safety Over the Next Few Hours</h2>
                <Button variant="secondary" size="sm" onClick={() => void loadTemporal()} disabled={temporal.kind === "loading"} loading={temporal.kind === "loading"}>
                  {temporal.kind === "loading" ? "Evaluating…" : "Check real hourly forecast"}
                </Button>
              </div>
              {temporal.kind === "loaded" && temporal.data && (
                <>
                  <div className="mt-3">
                    <LineSeriesChart
                      height={180}
                      highlightIndex={temporal.data.best_time_index}
                      series={
                        [
                          {
                            key: "wave",
                            label: "Wave Height",
                            color: "#38BDF8",
                            unit: "m",
                            points: temporal.data.series.map((row) => ({ timestamp: row.timestamp, value: row.environmental_context?.wave_height_m ?? null })),
                          },
                          {
                            key: "wind",
                            label: "Wind Speed",
                            color: "#F59E0B",
                            unit: "m/s",
                            points: temporal.data.series.map((row) => ({ timestamp: row.timestamp, value: row.environmental_context?.wind_speed_ms ?? null })),
                          },
                        ] as ChartSeries[]
                      }
                    />
                  </div>
                  <p className="mt-2 text-sm text-marine-ink-muted">
                    {temporal.data.best_time_index !== null
                      ? `Safest real forecast hour: ${new Date(temporal.data.series[temporal.data.best_time_index].timestamp).toLocaleString()} (lowest risk among hours that passed the deterministic Safety Guard).`
                      : "No hour in this window currently passes ORCA's deterministic safety checks."}
                  </p>
                  {temporal.meta?.limitations && (
                    <ul className="mt-2 list-disc space-y-1 pl-4 text-xs italic text-marine-ink-muted">
                      {temporal.meta.limitations.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>

            {/* --- CYCLONE / THUNDERSTORM (Phase 6) — the SAME shared cards
                the Dashboard's Thunderstorm card uses; cyclone detail lives
                only here since it is location-specific and the Dashboard
                only surfaces a compact hazards list. --------------------- */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <CycloneCard hazards={activeHazards} />
              <ThunderstormCard hazards={activeHazards} />
            </div>

            {/* --- MAP -------------------------------------------------------- */}
            <section className="relative h-[60vh] min-h-[460px] overflow-hidden rounded-2xl border border-marine-border">
              <RouteMap
                origin={location}
                destination={location}
                routeCoordinates={null}
                reducedMotion={reducedMotion}
                className="h-full w-full"
                deckLayers={deckLayers}
              />
              <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col items-end gap-3">
                <MapLegend />
              </div>
              {selected && (
                <div className="pointer-events-none absolute right-3 top-3">
                  <EvidencePanel feature={selected} onClose={() => setSelected(null)} />
                </div>
              )}
            </section>
          </div>

          <div className="flex flex-col gap-4">
            {/* --- ACTIVE HAZARDS ---------------------------------------------- */}
            <section className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Active Hazards</h2>
              {activeHazards.length === 0 && status.kind === "loaded" && (
                <p className="mt-3 text-sm text-marine-ink-muted">No active hazard detected for this location right now.</p>
              )}
              <div className="mt-3 space-y-2">
                {activeHazards.map((h, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setSelected({ layer: "hazard", properties: h as unknown as Record<string, unknown> })}
                    className="flex w-full items-center justify-between rounded-lg border border-marine-border bg-marine-surface-alt px-3.5 py-2.5 text-left text-sm text-marine-ink transition-colors hover:border-marine-blue/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
                  >
                    <span>{h.title}</span>
                    <span className={`font-semibold ${HAZARD_SEVERITY_TEXT[h.severity] ?? "text-marine-ink-muted"}`}>{h.severity}</span>
                  </button>
                ))}
              </div>
            </section>

            {/* --- RECOMMENDATION ------------------------------------------- */}
            {status.kind === "loaded" && (
              <section className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Recommendation</h2>
                <p className="mt-2 text-sm leading-relaxed text-marine-ink-muted">
                  {status.data!.decision_outcome === "RECOMMEND" && "Conditions currently pass ORCA's deterministic safety checks."}
                  {status.data!.decision_outcome === "RECOMMEND_WITH_CAUTION" && "Conditions are marginal — proceed with caution and monitor conditions."}
                  {status.data!.decision_outcome === "PROVIDE_ALTERNATIVES" && "Risk is elevated at this exact point — consider an alternative time or location."}
                  {status.data!.decision_outcome === "NO_SAFE_RECOMMENDATION" && "ORCA cannot recommend this location/time — a hard safety constraint was triggered."}
                  {!status.data!.decision_outcome && "No deterministic recommendation could be computed for this location."}
                </p>
              </section>
            )}

            {/* --- DATA AVAILABILITY ------------------------------------------ */}
            <section className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Data Availability</h2>
              <div className="mt-3 space-y-3 text-sm">
                {(sources ?? []).map((s) => (
                  <div key={s.hazard_type} className="flex items-start justify-between gap-2 border-b border-marine-border pb-3 last:border-0">
                    <div>
                      <p className="font-medium text-marine-ink">{s.hazard_type.replaceAll("_", " ")}</p>
                      <p className="text-xs text-marine-ink-muted">{s.reason}</p>
                    </div>
                    <span
                      className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
                        s.status === "AVAILABLE"
                          ? "border-marine-success/40 text-marine-success"
                          : s.status === "LIMITED"
                            ? "border-marine-warning/40 text-marine-warning"
                            : "border-marine-danger/40 text-marine-danger"
                      }`}
                    >
                      {s.status}
                    </span>
                  </div>
                ))}
              </div>
              {unavailable.length > 0 && (
                <p className="mt-3 text-xs italic text-marine-ink-muted">
                  For THIS specific query: {unavailable.map((u) => u.hazard_type).join(", ")} could not be fully assessed — see reasons above.
                </p>
              )}
            </section>

            <DataStatusPanel rows={statusRows} />
          </div>
        </div>

        {/* --- DATA & EVIDENCE (Phase 8) ------------------------------------ */}
        <EvidenceList
          title="Data & Evidence"
          rows={[
            ...(status.kind === "loaded"
              ? ([
                  { source: "ORCA Risk Engine + Safety Guard", variable: "Marine Safety Level", value: status.data!.level, timestamp: status.data!.generated_at, confidence: status.data!.confidence },
                ] as EvidenceRow[])
              : []),
            ...activeHazards.map(
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
            ...unavailable.map((u): EvidenceRow => ({ source: u.source, variable: u.hazard_type.replaceAll("_", " "), value: "UNAVAILABLE", freshness: "UNAVAILABLE", details: u.reason })),
          ]}
        />
      </div>
    </main>
  );
}
