import { useState } from "react";
import { Clock, Search, Sparkles } from "lucide-react";

import { Button, ButtonLink } from "../components/ui/Button";

import { RouteMap } from "../components/map/RouteMap";
import { LayerControlPanel, type LayerGroup } from "../components/map/LayerControlPanel";
import { MapLegend } from "../components/map/MapLegend";
import { EvidencePanel } from "../components/map/EvidencePanel";
import { DataStatusPanel, type StatusRow } from "../components/map/DataStatusPanel";
import { buildFishingCandidatesLayer, buildGeofenceLayer, type SelectedFeature } from "../components/map/mapLayers";
import { LineSeriesChart, type ChartSeries } from "../components/charts/LineSeriesChart";
import { ComparisonBarChart } from "../components/charts/ComparisonBarChart";
import { EvidenceList, type EvidenceRow } from "../components/evidence/Evidence";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useMapLayer } from "../hooks/useMapLayer";
import {
  askOrca,
  compareFishingAreas,
  getFishingCandidates,
  getGeofencesLayer,
  getTemporalFishingSuitability,
  type FishingCandidateProps,
  type FishingCandidatesMeta,
  type TemporalFishingResponse,
} from "../lib/api";

const REGION_CENTER = { latitude: 13.075, longitude: 74.275 };

type CandidateFeature = { properties: FishingCandidateProps; geometry: { coordinates: [number, number] } };

function candidateLabel(_c: CandidateFeature, index: number): string {
  return `Area ${String.fromCharCode(65 + index)}`; // Area A, Area B, Area C, ...
}

/**
 * The Fishing Intelligence page — DISCOVER (find candidate areas),
 * ANALYZE (why an area is/isn't suitable), COMPARE (deterministic
 * side-by-side). Reuses the existing RouteMap (MapLibre + deck.gl) and
 * EvidencePanel/LayerControlPanel/MapLegend/DataStatusPanel — no second
 * map implementation. Every candidate, score, and ranking shown here comes
 * from `GET/POST /api/v1/fishing/*` (backend/app/api/v1/fishing.py),
 * itself a composition of the existing deterministic Risk/Suitability/
 * Safety/Decision engines — nothing is computed in this file.
 */
export function FishingPage() {
  const reducedMotion = usePrefersReducedMotion();
  const [query, setQuery] = useState("");
  const [askResult, setAskResult] = useState<{ explanation: string; usedFallback: boolean } | null>(null);
  const [asking, setAsking] = useState(false);
  const [selected, setSelected] = useState<SelectedFeature | null>(null);
  const [compareSelection, setCompareSelection] = useState<number[]>([]);
  const [compareResult, setCompareResult] = useState<{ reason: string; betterIndex: number | null } | null>(null);
  const [comparing, setComparing] = useState(false);
  const [showCandidates, setShowCandidates] = useState(true);
  const [showGeofences, setShowGeofences] = useState(true);
  // Phase 7 (task §9/§11/§35) — the real per-hour time window for whichever
  // area was last clicked (`selected`); fetched on demand, never eagerly
  // for every candidate at once.
  const [temporal, setTemporal] = useState<TemporalFishingResponse["data"] | null>(null);
  const [temporalLoading, setTemporalLoading] = useState(false);

  const candidates = useMapLayer<FishingCandidatesMeta>(showCandidates, () => getFishingCandidates());
  const geofences = useMapLayer(showGeofences, getGeofencesLayer);

  const rankedFeatures: CandidateFeature[] =
    candidates.state.kind === "loaded"
      ? (candidates.state.data.features.filter((f) => f.properties.status === "ranked") as unknown as CandidateFeature[]).sort(
          (a, b) => (a.properties.rank ?? 999) - (b.properties.rank ?? 999),
        )
      : [];
  const topAreas = rankedFeatures.slice(0, 6);

  const deckLayers = [];
  if (showGeofences && geofences.state.kind === "loaded") deckLayers.push(buildGeofenceLayer(geofences.state.data, setSelected));
  if (showCandidates && candidates.state.kind === "loaded") deckLayers.push(buildFishingCandidatesLayer(candidates.state.data, setSelected));

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setAsking(true);
    setAskResult(null);
    try {
      const response = await askOrca({ query });
      if (response.data?.status === "clarification_needed") {
        setAskResult({ explanation: response.data.clarification?.reason ?? "ORCA needs more detail to answer that.", usedFallback: false });
      } else if (response.data?.explanation) {
        setAskResult({ explanation: response.data.explanation, usedFallback: !!response.data.used_fallback_template });
        if (response.data.fishing_candidates) candidates.refresh();
      }
    } catch {
      setAskResult({ explanation: "ORCA's backend is not reachable right now.", usedFallback: false });
    } finally {
      setAsking(false);
    }
  };

  const toggleCompareSelection = (index: number) => {
    setCompareResult(null);
    setCompareSelection((prev) => {
      if (prev.includes(index)) return prev.filter((i) => i !== index);
      if (prev.length >= 2) return [prev[1], index];
      return [...prev, index];
    });
  };

  const loadTemporal = async (latitude: number, longitude: number) => {
    setTemporalLoading(true);
    setTemporal(null);
    try {
      const response = await getTemporalFishingSuitability(latitude, longitude, 6);
      setTemporal(response.data);
    } finally {
      setTemporalLoading(false);
    }
  };

  const runCompare = async () => {
    if (compareSelection.length !== 2) return;
    setComparing(true);
    setCompareResult(null);
    try {
      const points = compareSelection.map((i) => {
        const [lon, lat] = topAreas[i].geometry.coordinates;
        return { latitude: lat, longitude: lon };
      });
      const response = await compareFishingAreas(points);
      if (response.data) setCompareResult({ reason: response.data.reason, betterIndex: response.data.better_candidate_index });
    } finally {
      setComparing(false);
    }
  };

  const layerGroups: LayerGroup[] = [
    { title: "Base Map", layers: [{ key: "basemap", label: "Marine Base Map", available: true }] },
    {
      title: "Fishing Intelligence",
      layers: [
        { key: "candidates", label: "Candidate Areas", available: true },
        { key: "geofences", label: "Geofences / Restricted Zones", available: true },
      ],
    },
    { title: "Fishing", layers: [{ key: "pfz", label: "INCOIS PFZ Reference", available: false, unavailableReason: "No machine-readable official INCOIS PFZ dataset is integrated — see the PFZ Reference card for what is/isn't available." }] },
  ];
  const enabledMap: Record<string, boolean> = { candidates: showCandidates, geofences: showGeofences, pfz: false };
  const toggleLayer = (key: string) => {
    if (key === "candidates") setShowCandidates((v) => !v);
    if (key === "geofences") setShowGeofences((v) => !v);
  };

  const statusRows: StatusRow[] = [
    { label: "Candidates", state: showCandidates ? candidates.state : "not-enabled", sampleNote: candidates.state.kind === "loaded" ? `${candidates.state.meta.ranked_count} ranked / ${candidates.state.meta.avoid_count} avoid` : undefined },
    { label: "Geofences", state: showGeofences ? geofences.state : "not-enabled" },
    { label: "PFZ", state: "static-unavailable" },
  ];

  return (
    <main className="min-h-screen bg-marine-surface-alt pt-20">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-10 sm:px-10 lg:px-16 lg:py-14">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">Deterministic Decision Support</p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-marine-ink sm:text-4xl">Fishing Intelligence.</h1>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-marine-ink-muted">
            ORCA Fishing Suitability is environmental decision support, computed by ORCA's own deterministic engines — it is{" "}
            <strong className="text-marine-ink">not</strong> fish detection and does not guarantee a catch. It is a separate system
            from the official INCOIS PFZ advisory (see the PFZ Reference card below). For what-if scenarios ("what if waves reach 3
            metres there?") or the best time to fish across a window, ask{" "}
            <a href="/ask-orca" className="text-marine-blue underline hover:text-marine-cyan">
              Ask ORCA
            </a>
            , or use the Time Window panel for a specific area.
          </p>
        </div>

        <form onSubmit={handleAsk} className="flex gap-2">
          <label htmlFor="fishing-search" className="sr-only">
            Ask ORCA about fishing conditions
          </label>
          <input
            id="fishing-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='e.g. "Find suitable fishing areas near Mangaluru tomorrow morning"'
            className="flex-1 rounded-full border border-marine-cyan/25 bg-marine-surface px-4 py-2.5 text-sm text-marine-ink placeholder:text-marine-ink-muted focus:border-marine-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
          />
          <Button type="submit" disabled={asking || !query.trim()} loading={asking}>
            <Search size={15} />
            {asking ? "Asking…" : "Ask ORCA"}
          </Button>
        </form>

        {askResult && (
          <div className="rounded-xl border border-marine-border bg-marine-surface p-4 text-sm text-marine-ink shadow-sm">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-marine-blue">
              <Sparkles size={13} /> ORCA{askResult.usedFallback ? " (deterministic template)" : ""}
            </p>
            <p className="mt-2 leading-relaxed">{askResult.explanation}</p>
          </div>
        )}

        {/* PFZ REFERENCE — Phase 5: correct, honest terminology. No
            machine-readable INCOIS PFZ dataset and no reference snapshot
            file (data/reference/pfz/) exist in this deployment — never
            fabricated as a live layer or inferred from an image. */}
        <div className="rounded-2xl border border-marine-border bg-marine-surface p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold uppercase tracking-wide text-marine-blue">INCOIS PFZ Reference</p>
              <p className="mt-1 text-sm text-marine-ink-muted">Official Potential Fishing Zone advisory — Indian National Centre for Ocean Information Services (INCOIS).</p>
            </div>
            <span className="rounded-full border border-marine-border bg-marine-surface-alt px-3 py-1 text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">
              Reference Snapshot — Unavailable
            </span>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-marine-ink-muted">
            No machine-readable INCOIS PFZ dataset is integrated, and no reference snapshot file is present in this deployment. ORCA
            never infers PFZ coordinates from an advisory image and never labels its own suitability areas below as official PFZ.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_400px]">
          <section className="relative h-[70vh] min-h-[520px] overflow-hidden rounded-2xl border border-marine-border">
            <RouteMap
              origin={REGION_CENTER}
              destination={REGION_CENTER}
              routeCoordinates={null}
              reducedMotion={reducedMotion}
              className="h-full w-full"
              deckLayers={deckLayers}
            />
            <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-3">
              <LayerControlPanel groups={layerGroups} enabled={enabledMap} onToggle={toggleLayer} onRefresh={() => candidates.refresh()} refreshing={candidates.state.kind === "loading"} />
            </div>
            <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-3">
              <DataStatusPanel rows={statusRows} />
            </div>
            <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col items-end gap-3">
              <MapLegend />
            </div>
            {selected && (
              <div className="pointer-events-none absolute right-3 top-3">
                <EvidencePanel feature={selected} onClose={() => setSelected(null)} />
              </div>
            )}
          </section>

          <section className="flex flex-col gap-4">
            <div className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Best Available Areas</h2>
              {candidates.state.kind === "loading" && <p className="mt-3 text-sm text-marine-ink-muted">Evaluating candidate areas…</p>}
              {candidates.state.kind === "error" && <p className="mt-3 text-sm text-marine-danger">{candidates.state.message}</p>}
              {topAreas.length === 0 && candidates.state.kind === "loaded" && (
                <p className="mt-3 text-sm text-marine-ink-muted">No candidate area currently passes ORCA's deterministic safety/risk/suitability checks.</p>
              )}
              <div className="mt-4 space-y-3">
                {topAreas.map((area, i) => (
                  <div
                    key={i}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelected({ layer: "fishing-candidate", properties: area.properties as unknown as Record<string, unknown> })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") setSelected({ layer: "fishing-candidate", properties: area.properties as unknown as Record<string, unknown> });
                    }}
                    className="cursor-pointer rounded-xl border border-marine-border bg-marine-surface p-4 text-marine-ink shadow-sm transition-colors hover:border-marine-blue/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2.5 text-lg font-semibold">
                        <input
                          type="checkbox"
                          checked={compareSelection.includes(i)}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggleCompareSelection(i)}
                          className="h-4 w-4 accent-marine-cyan"
                          aria-label={`Select ${candidateLabel(area, i)} for comparison`}
                        />
                        {candidateLabel(area, i)}
                      </span>
                      <button
                        type="button"
                        title="Show real time-window analysis for this area"
                        onClick={(e) => {
                          e.stopPropagation();
                          const [lon, lat] = area.geometry.coordinates;
                          void loadTemporal(lat, lon);
                        }}
                        className="rounded-full p-1.5 text-marine-ink-muted hover:bg-marine-cyan/15 hover:text-marine-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
                        aria-label={`Show time window for ${candidateLabel(area, i)}`}
                      >
                        <Clock size={16} />
                      </button>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs uppercase tracking-wide text-marine-ink-muted">Suitability</p>
                        <p className="mt-0.5 font-semibold text-marine-success">{area.properties.suitability_category}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-marine-ink-muted">Risk</p>
                        <p className="mt-0.5 font-semibold text-marine-ink">{area.properties.risk_level}</p>
                      </div>
                      {area.properties.environmental_context?.wave_height_m != null && (
                        <div>
                          <p className="text-xs uppercase tracking-wide text-marine-ink-muted">Wave</p>
                          <p className="mt-0.5 text-marine-ink-muted">{area.properties.environmental_context.wave_height_m.toFixed(2)} m</p>
                        </div>
                      )}
                      {area.properties.distance_km != null && (
                        <div>
                          <p className="text-xs uppercase tracking-wide text-marine-ink-muted">Distance</p>
                          <p className="mt-0.5 text-marine-ink-muted">{area.properties.distance_km.toFixed(1)} km</p>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {(temporalLoading || temporal) && (
              <div className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Time Window (real hourly forecast)</h2>
                {temporalLoading && <p className="mt-3 text-sm text-marine-ink-muted">Evaluating real forecast hours…</p>}
                {temporal && (
                  <>
                    <div className="mt-3">
                      <LineSeriesChart
                        height={180}
                        highlightIndex={temporal.recommended_index}
                        series={
                          [
                            {
                              key: "wave",
                              label: "Wave Height",
                              color: "#38BDF8",
                              unit: "m",
                              points: temporal.series.map((row) => ({ timestamp: row.timestamp, value: row.environmental_context?.wave_height_m ?? null })),
                            },
                            {
                              key: "wind",
                              label: "Wind Speed",
                              color: "#F59E0B",
                              unit: "m/s",
                              points: temporal.series.map((row) => ({ timestamp: row.timestamp, value: row.environmental_context?.wind_speed_ms ?? null })),
                            },
                          ] as ChartSeries[]
                        }
                      />
                    </div>
                    <p className="mt-2 text-sm text-marine-ink-muted">
                      {temporal.recommended_index !== null
                        ? `Best available time: ${new Date(temporal.series[temporal.recommended_index].timestamp).toLocaleString()} (highest suitability among hours that passed safety checks).`
                        : "No hour in this window currently passes ORCA's deterministic safety checks."}
                    </p>
                  </>
                )}
              </div>
            )}

            {compareSelection.length === 2 && (
              <div className="rounded-2xl border border-marine-border bg-marine-surface shadow-sm p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Compare Areas</h2>
                <Button variant="secondary" size="sm" onClick={runCompare} disabled={comparing} loading={comparing} className="mt-3 w-full">
                  {comparing ? "Comparing…" : `Compare ${candidateLabel(topAreas[compareSelection[0]], compareSelection[0])} vs ${candidateLabel(topAreas[compareSelection[1]], compareSelection[1])}`}
                </Button>
                {compareResult && (
                  <>
                    <ComparisonBarChart
                      height={130}
                      groups={compareSelection.map((i, idx) => ({
                        key: `area-${i}`,
                        label: candidateLabel(topAreas[i], i),
                        value: topAreas[i].properties.suitability_score ?? 0,
                        color: idx === 0 ? "#38BDF8" : "#F59E0B",
                        sublabel: topAreas[i].properties.risk_level ?? undefined,
                      }))}
                    />
                    <p className="mt-2 text-sm leading-relaxed text-marine-ink-muted">{compareResult.reason}</p>
                  </>
                )}
              </div>
            )}

            <ButtonLink to="/marine-map" variant="ghost" size="md" className="w-full">
              View full Marine Intelligence Map →
            </ButtonLink>
          </section>
        </div>

        {/* --- DATA & EVIDENCE (Phase 8) ------------------------------------ */}
        {topAreas.length > 0 && (
          <EvidenceList
            title="Data & Evidence"
            rows={topAreas.slice(0, 3).map(
              (area, i): EvidenceRow => ({
                source: area.properties.source,
                variable: `${candidateLabel(area, i)} — ORCA Fishing Suitability`,
                value: area.properties.suitability_score != null ? `${Math.round(area.properties.suitability_score * 100)}/100` : "n/a",
                timestamp: area.properties.timestamp,
                confidence: area.properties.confidence,
                details: "ORCA's own deterministic suitability score — not fish detection, not a guaranteed catch.",
              }),
            )}
          />
        )}
      </div>
    </main>
  );
}
