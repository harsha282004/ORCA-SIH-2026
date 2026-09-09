import { useEffect, useMemo, useState } from "react";

import { RouteMap } from "../components/map/RouteMap";
import { LayerControlPanel, type LayerGroup } from "../components/map/LayerControlPanel";
import { MapLegend } from "../components/map/MapLegend";
import { EvidencePanel } from "../components/map/EvidencePanel";
import { DataStatusPanel, type StatusRow } from "../components/map/DataStatusPanel";
import { HeatmapControl, type HeatmapOption } from "../components/map/HeatmapControl";
import { TimeSlider } from "../components/map/TimeSlider";
import { buildFishingCandidatesLayer, buildHazardsLayer, buildHeatmapLayer, heatmapValueExtent, type HeatmapVariable } from "../components/map/mapLayers";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useMapLayer } from "../hooks/useMapLayer";
import { useMarineLayers } from "../hooks/useMarineLayers";
import { useMarineTimeseries } from "../hooks/useMarineTimeseries";
import { getFishingCandidates, getSafetyHazards, type FishingCandidatesMeta, type SafetyHazardsMeta } from "../lib/api";

// The ORCA demo region's own center — reused verbatim from
// backend/app/config.py's DEMO_BBOX (12.70-13.45N, 73.50-75.05E), never
// invented — used as the single reference point the time slider queries
// `GET /api/v1/layers/marine-timeseries` for (this page has no
// origin/destination selection; that remains the Route Planner's job).
const REGION_CENTER = { latitude: 13.075, longitude: 74.275 };
const MAP_CENTER_MARKER = { latitude: REGION_CENTER.latitude, longitude: REGION_CENTER.longitude };

/**
 * The Marine Intelligence Map — "Explore marine conditions and
 * intelligence across the ORCA region." Reuses the exact same RouteMap
 * (MapLibre + deck.gl) and layer-fetching machinery (`useMarineLayers`)
 * the Route Planner uses — no second map engine, no duplicated fetch
 * logic. Unlike the Route Planner, this page has no origin/destination
 * form; it exists to inspect the real, honestly-labeled data foundation
 * itself, including the real hourly time slider.
 */
export function MarineMapPage() {
  const reducedMotion = usePrefersReducedMotion();
  // The time slider's currently-selected REAL timestamp (an actual value
  // from the fetched series, never invented) — fed into `useMarineLayers`
  // below so moving the slider genuinely re-requests risk/oceanography/
  // suitability for that hour, not just relabels the same response.
  const [selectedAt, setSelectedAt] = useState<string | undefined>(undefined);

  const marine = useMarineLayers(
    {
      risk: true,
      geofences: true,
      bathymetry: true,
      chlorophyll: true,
    },
    selectedAt,
  );

  const timeSliderEnabled = marine.enabled.sst || marine.enabled.currents || marine.enabled.waves || marine.enabled.wind;
  const timeseries = useMarineTimeseries(timeSliderEnabled, REGION_CENTER.latitude, REGION_CENTER.longitude);

  // Phase 3 §17 — fishing candidate areas, surfaced here too (not only on
  // the dedicated /fishing page), reusing the SAME GET /api/v1/fishing
  // /candidates endpoint and the SAME deck.gl layer builder.
  const [showCandidates, setShowCandidates] = useState(false);
  const candidates = useMapLayer<FishingCandidatesMeta>(showCandidates, () => getFishingCandidates());

  // Phase 4 — real detected marine hazards (GET /api/v1/safety/hazards).
  // The endpoint is point-based (a cyclone's relevance radius is ~800km —
  // far larger than the demo bbox, so a grid sweep would be redundant), so
  // this checks the region's own centroid, the SAME reference point the
  // time slider already uses.
  const [showHazards, setShowHazards] = useState(false);
  const hazards = useMapLayer<SafetyHazardsMeta>(showHazards, () => getSafetyHazards(REGION_CENTER.latitude, REGION_CENTER.longitude));

  // --- Phase 12: real spatial heatmap ---------------------------------------
  // Reuses the SAME oceanography/risk/suitability/chlorophyll fetches
  // useMarineLayers already performs for the point/polygon layers above —
  // no second data source, no new endpoint. Selecting a wave/wind/SST
  // heatmap variable auto-enables the oceanography fetch that already backs
  // the Waves/Wind/SST point layers, exactly like toggling those checkboxes
  // would, so there is only ever one live fetch per underlying source.
  const [heatmapVariable, setHeatmapVariable] = useState<HeatmapVariable | null>(null);
  useEffect(() => {
    if (heatmapVariable === "wave_height" || heatmapVariable === "wind_speed" || heatmapVariable === "sst") {
      if (!marine.enabled.waves && !marine.enabled.wind && !marine.enabled.sst) marine.toggleLayer("waves");
    } else if (heatmapVariable === "risk" && !marine.enabled.risk) {
      marine.toggleLayer("risk");
    } else if (heatmapVariable === "suitability" && !marine.enabled.suitability) {
      marine.toggleLayer("suitability");
    } else if (heatmapVariable === "chlorophyll" && !marine.enabled.chlorophyll) {
      marine.toggleLayer("chlorophyll");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatmapVariable]);

  const heatmapSourceState =
    heatmapVariable === "wave_height" || heatmapVariable === "wind_speed" || heatmapVariable === "sst"
      ? marine.layers.oceanography.state
      : heatmapVariable === "risk"
        ? marine.layers.riskSurface.state
        : heatmapVariable === "suitability"
          ? marine.layers.suitability.state
          : heatmapVariable === "chlorophyll"
            ? marine.layers.chlorophyll.state
            : null;

  const heatmapData = heatmapSourceState?.kind === "loaded" ? heatmapSourceState.data : null;
  const heatmapExtent = useMemo(() => (heatmapData && heatmapVariable ? heatmapValueExtent(heatmapData, heatmapVariable) : null), [heatmapData, heatmapVariable]);
  const heatmapDeckLayer = useMemo(
    () => (heatmapData && heatmapVariable && heatmapExtent ? buildHeatmapLayer(heatmapData, heatmapVariable) : null),
    [heatmapData, heatmapVariable, heatmapExtent],
  );
  const heatmapStatus: "idle" | "loading" | "ready" | "unavailable" | "error" = !heatmapVariable
    ? "idle"
    : !heatmapSourceState || heatmapSourceState.kind === "loading" || heatmapSourceState.kind === "idle"
      ? "loading"
      : heatmapSourceState.kind === "error"
        ? "error"
        : heatmapSourceState.kind === "unavailable"
          ? "unavailable"
          : heatmapExtent
            ? "ready"
            : "unavailable";

  const HEATMAP_OPTIONS: HeatmapOption[] = [
    { value: "wave_height", label: "Wave Height", unit: "m", available: true },
    { value: "wind_speed", label: "Wind Speed", unit: "m/s", available: true },
    { value: "sst", label: "SST", unit: "°C", available: true },
    { value: "risk", label: "Marine Risk", unit: "score", available: true },
    { value: "suitability", label: "Fishing Suitability", unit: "score", available: true },
    { value: "chlorophyll", label: "Chlorophyll-a", unit: "mg/m³", available: true },
  ];

  const allDeckLayers = [...marine.deckLayers];
  if (heatmapDeckLayer) allDeckLayers.push(heatmapDeckLayer);
  if (showCandidates && candidates.state.kind === "loaded") allDeckLayers.push(buildFishingCandidatesLayer(candidates.state.data, marine.setSelected));
  if (showHazards && hazards.state.kind === "loaded") allDeckLayers.push(buildHazardsLayer(hazards.state.data, marine.setSelected));

  const handleTimeChange = (index: number) => {
    timeseries.setSelectedIndex(index);
    if (timeseries.state.kind === "loaded") setSelectedAt(timeseries.state.series[index]?.timestamp);
  };

  const layerGroups: LayerGroup[] = [
    { title: "Base Map", layers: [{ key: "basemap", label: "Marine Base Map", available: true }] },
    {
      title: "Marine Conditions",
      layers: [
        { key: "sst", label: "SST (Open-Meteo)", available: true },
        { key: "incoisSst", label: "SST (INCOIS, sampled)", available: true },
        { key: "chlorophyll", label: "Chlorophyll-a (INCOIS)", available: true },
        { key: "currents", label: "Currents", available: true },
        { key: "waves", label: "Waves", available: true },
        { key: "wind", label: "Wind", available: true },
        { key: "bathymetry", label: "Bathymetry (GEBCO, sampled)", available: true },
      ],
    },
    {
      title: "ORCA Intelligence",
      layers: [
        { key: "suitability", label: "Fishing Suitability", available: true },
        { key: "risk", label: "ORCA Risk", available: true },
        { key: "geofences", label: "Geofences", available: true },
      ],
    },
    {
      title: "Fishing",
      layers: [
        { key: "candidates", label: "Fishing Candidate Areas", available: true },
        {
          key: "pfz",
          label: "INCOIS PFZ",
          available: false,
          unavailableReason: "No verified machine-readable official INCOIS PFZ geometry source is currently integrated (investigated in Phase 1 — see docs/PHASE_1_MARINE_DATA_FOUNDATION_REPORT.md).",
        },
      ],
    },
    {
      title: "Routing",
      layers: [
        { key: "route", label: "Route (plan on Route Planner)", available: false, unavailableReason: "This page does not plan routes — use the Route Planner page, then return here to explore conditions along the way." },
      ],
    },
    {
      title: "Safety (Phase 4)",
      layers: [
        { key: "hazards", label: "Marine Hazards (real cyclone/wave/wind)", available: true },
        { key: "lightning", label: "Lightning / Thunderstorm (authoritative)", available: false, unavailableReason: "No public real-time lightning-detection API exists for this region (DAMINI/IMD has none). A coarse weather-code proxy is included in the hazards layer, clearly labeled as non-authoritative." },
      ],
    },
  ];

  const statusRows: StatusRow[] = [
    { label: "Bathymetry", state: marine.enabled.bathymetry ? marine.layers.bathymetry.state : "not-enabled", sampleNote: marine.layers.bathymetry.state.kind === "loaded" ? `${marine.layers.bathymetry.state.meta.sample_count ?? "?"} samples` : undefined },
    { label: "Risk", state: marine.enabled.risk ? marine.layers.riskSurface.state : "not-enabled" },
    { label: "Geofences", state: marine.enabled.geofences ? marine.layers.geofences.state : "not-enabled" },
    { label: "Suitability", state: marine.enabled.suitability ? marine.layers.suitability.state : "not-enabled" },
    { label: "SST (Open-Meteo)", state: marine.enabled.sst ? marine.layers.oceanography.state : "not-enabled" },
    { label: "SST (INCOIS)", state: marine.enabled.incoisSst ? marine.incoisSstState : "not-enabled", sampleNote: marine.incoisSstState.kind === "loaded" ? `${marine.incoisSstState.meta.sample_count ?? "?"} samples` : undefined },
    { label: "Chlorophyll", state: marine.enabled.chlorophyll ? marine.layers.chlorophyll.state : "not-enabled", sampleNote: marine.layers.chlorophyll.state.kind === "loaded" ? `${marine.layers.chlorophyll.state.meta.sample_count ?? "?"} samples` : undefined },
    { label: "Fishing Candidates", state: showCandidates ? candidates.state : "not-enabled", sampleNote: candidates.state.kind === "loaded" ? `${candidates.state.meta.ranked_count} ranked` : undefined },
    { label: "PFZ", state: "static-unavailable" },
    { label: "Marine Hazards", state: showHazards ? hazards.state : "not-enabled", sampleNote: hazards.state.kind === "loaded" ? `${hazards.state.meta.hazard_count} detected` : undefined },
    { label: "Lightning (authoritative)", state: "static-unavailable" },
  ];

  const layerError =
    (marine.enabled.risk && marine.layers.riskSurface.state.kind === "error" && marine.layers.riskSurface.state.message) ||
    (marine.enabled.geofences && marine.layers.geofences.state.kind === "error" && marine.layers.geofences.state.message) ||
    (marine.enabled.suitability && marine.layers.suitability.state.kind === "error" && marine.layers.suitability.state.message) ||
    (timeSliderEnabled && marine.layers.oceanography.state.kind === "error" && marine.layers.oceanography.state.message) ||
    (marine.enabled.chlorophyll && marine.layers.chlorophyll.state.kind === "error" && marine.layers.chlorophyll.state.message) ||
    (marine.enabled.bathymetry && marine.layers.bathymetry.state.kind === "error" && marine.layers.bathymetry.state.message) ||
    null;

  return (
    <main className="min-h-screen bg-marine-deep pt-20">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-10 sm:px-10 lg:px-16 lg:py-14">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Marine Data Foundation</p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-marine-white sm:text-4xl">Marine Intelligence Map.</h1>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-marine-white/70">
            Explore real marine conditions and ORCA's deterministic intelligence across the Mangaluru–Udupi demo region — bathymetry,
            chlorophyll, and SST here are real, acquired samples, not continuous fields; risk and fishing suitability are computed live by
            ORCA's own deterministic engines. To plan a route, use the{" "}
            <a href="/route-planner" className="text-marine-cyan-light underline hover:text-marine-cyan">
              Route Planner
            </a>
            ; for ranked candidate fishing areas and comparisons, visit{" "}
            <a href="/fishing" className="text-marine-cyan-light underline hover:text-marine-cyan">
              Fishing Intelligence
            </a>
            ; for a combined marine safety status and detected hazards, visit{" "}
            <a href="/safety" className="text-marine-cyan-light underline hover:text-marine-cyan">
              Marine Safety
            </a>
            .
          </p>
        </div>

        {/* Explicit viewport-relative height, not flex-grow: this page's
            wrapper is a column flex with no defined height of its own (no
            sidebar to size against, unlike the Route Planner's row layout),
            so `flex-1` alone has nothing to grow into and the MapLibre
            canvas would size itself to a near-zero height at mount. */}
        <section className="relative h-[70vh] min-h-[480px] overflow-hidden rounded-2xl border border-marine-cyan/15 lg:h-[75vh]">
          <RouteMap
            origin={MAP_CENTER_MARKER}
            destination={MAP_CENTER_MARKER}
            routeCoordinates={null}
            reducedMotion={reducedMotion}
            className="h-full w-full"
            deckLayers={allDeckLayers}
          />

          <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-3">
            <LayerControlPanel
              groups={layerGroups}
              enabled={{ ...marine.enabled, candidates: showCandidates, hazards: showHazards }}
              onToggle={(k) => {
                if (k === "candidates") return setShowCandidates((v) => !v);
                if (k === "hazards") return setShowHazards((v) => !v);
                marine.toggleLayer(k as never);
              }}
              onRefresh={() => {
                marine.refresh();
                if (showCandidates) candidates.refresh();
                if (showHazards) hazards.refresh();
              }}
              refreshing={marine.refreshing || candidates.state.kind === "loading" || hazards.state.kind === "loading"}
            />
            <HeatmapControl
              options={HEATMAP_OPTIONS}
              value={heatmapVariable}
              onChange={setHeatmapVariable}
              status={heatmapStatus}
              statusMessage={heatmapSourceState?.kind === "error" ? heatmapSourceState.message : undefined}
              extent={heatmapExtent}
            />
          </div>

          <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-3">
            <DataStatusPanel rows={statusRows} />
          </div>

          <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col items-end gap-3">
            <MapLegend />
          </div>

          {marine.selected && (
            <div className="pointer-events-none absolute right-3 top-3">
              <EvidencePanel feature={marine.selected} onClose={() => marine.setSelected(null)} />
            </div>
          )}

          {marine.enabled.bathymetry && marine.layers.bathymetry.state.kind === "unavailable" && (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg border border-marine-warning/40 bg-marine-deep/95 px-4 py-2 text-xs text-marine-warning shadow-lg">
              Bathymetry — DATA INTEGRATION NOT CURRENTLY AVAILABLE ({marine.layers.bathymetry.state.reason})
            </div>
          )}

          {layerError && (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg border border-marine-danger/40 bg-marine-deep/95 px-4 py-2 text-xs text-marine-danger shadow-lg">
              {layerError}
            </div>
          )}
        </section>

        {timeSliderEnabled && (
          <TimeSlider state={timeseries.state} selectedIndex={timeseries.selectedIndex} onChange={handleTimeChange} point={timeseries.selectedPoint} />
        )}
      </div>
    </main>
  );
}
