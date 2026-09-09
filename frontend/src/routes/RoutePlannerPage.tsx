import { useCallback, useMemo, useState } from "react";

import { RoutePlanner } from "../components/app/RoutePlanner";
import { RouteMap } from "../components/map/RouteMap";
import { LayerControlPanel, type LayerGroup } from "../components/map/LayerControlPanel";
import { MapLegend } from "../components/map/MapLegend";
import { EvidencePanel } from "../components/map/EvidencePanel";
import { DataStatusPanel, type StatusRow } from "../components/map/DataStatusPanel";
import { buildAlternativeRoutesLayer, buildHazardsLayer, buildRouteRiskLayer } from "../components/map/mapLayers";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useMarineLayers } from "../hooks/useMarineLayers";
import type { Coordinate, RouteComparisonData, RouteResultData } from "../lib/api";

const DEFAULT_ORIGIN = { latitude: 12.8, longitude: 74.2 };
const DEFAULT_DESTINATION = { latitude: 13.3, longitude: 74.1 };

interface PlannerMapState {
  origin: Coordinate;
  destination: Coordinate;
  routes: RouteResultData[];
  comparison: RouteComparisonData | null;
  selectedLabel: string | null;
}

/**
 * The Route Planner — "Plan and evaluate a route from origin to
 * destination." Reuses the same `useMarineLayers` fetch/toggle machinery
 * the Marine Intelligence Map (`/marine-map`) uses, adding only the
 * route-planning form and the route-risk deck.gl layer on top — no second
 * copy of the layer-fetching logic, no duplicate map engine. Phase 5 adds
 * alternative-route comparison and real hazard-proximity visualization for
 * the currently SELECTED route, without a second map implementation.
 */
export function RoutePlannerPage() {
  const reducedMotion = usePrefersReducedMotion();
  const [mapState, setMapState] = useState<PlannerMapState>({
    origin: DEFAULT_ORIGIN,
    destination: DEFAULT_DESTINATION,
    routes: [],
    comparison: null,
    selectedLabel: null,
  });
  const marine = useMarineLayers({ risk: true, geofences: true });

  const handleStateChange = useCallback((next: PlannerMapState) => setMapState(next), []);

  const selectedRoute = mapState.routes.find((r) => r.label === mapState.selectedLabel) ?? null;

  // Real hazards near the SELECTED route only (`hazards_near_route`,
  // Phase 4) — rendered as a real GeoJSON FeatureCollection through the
  // SAME `buildHazardsLayer` the Marine Map/Safety page already use, never
  // a second hazard-rendering implementation.
  const routeHazardsCollection = useMemo(() => {
    if (!selectedRoute || selectedRoute.hazards_near_route.length === 0) return null;
    return {
      type: "FeatureCollection" as const,
      features: selectedRoute.hazards_near_route
        .filter((h) => h.latitude != null && h.longitude != null)
        .map((h) => ({
          type: "Feature" as const,
          properties: h as unknown as Record<string, unknown>,
          geometry: { type: "Point", coordinates: [h.longitude as number, h.latitude as number] },
        })),
    };
  }, [selectedRoute]);

  const deckLayers = useMemo(() => {
    const layers = [...marine.deckLayers];
    if (mapState.routes.length > 1) {
      layers.push(buildAlternativeRoutesLayer(mapState.routes, mapState.selectedLabel, marine.setSelected));
    }
    if (selectedRoute && selectedRoute.path_cells.length > 1) {
      layers.push(buildRouteRiskLayer(selectedRoute.path_cells, marine.setSelected));
    }
    if (routeHazardsCollection) {
      layers.push(buildHazardsLayer(routeHazardsCollection, marine.setSelected));
    }
    return layers;
  }, [marine.deckLayers, marine.setSelected, mapState.routes, mapState.selectedLabel, selectedRoute, routeHazardsCollection]);

  const layerGroups: LayerGroup[] = [
    { title: "Base Map", layers: [{ key: "basemap", label: "Marine Base Map", available: true }] },
    { title: "Marine Terrain", layers: [{ key: "bathymetry", label: "Bathymetry", available: true }] },
    {
      title: "Risk & Safety",
      layers: [
        { key: "risk", label: "ORCA Risk", available: true },
        { key: "geofences", label: "Geofences / Restricted Zones", available: true },
      ],
    },
    {
      title: "Fisheries",
      layers: [
        { key: "pfz", label: "INCOIS PFZ Reference", available: false, unavailableReason: "No official INCOIS PFZ feed is integrated in this deployment." },
        { key: "suitability", label: "ORCA Fishing Suitability", available: true },
      ],
    },
    {
      title: "Oceanography",
      layers: [
        { key: "sst", label: "SST", available: true },
        { key: "chlorophyll", label: "Chlorophyll (INCOIS)", available: true },
        { key: "currents", label: "Currents", available: true },
        { key: "waves", label: "Waves", available: true },
      ],
    },
    { title: "Route", layers: [{ key: "route", label: "ORCA Route (selected + alternatives + hazards)", available: true }] },
  ];

  const oceanographyOn = marine.enabled.sst || marine.enabled.currents || marine.enabled.waves;
  const statusRows: StatusRow[] = [
    { label: "Bathymetry", state: marine.enabled.bathymetry ? marine.layers.bathymetry.state : "not-enabled" },
    { label: "Risk", state: marine.enabled.risk ? marine.layers.riskSurface.state : "not-enabled" },
    { label: "Geofences", state: marine.enabled.geofences ? marine.layers.geofences.state : "not-enabled" },
    { label: "Suitability", state: marine.enabled.suitability ? marine.layers.suitability.state : "not-enabled" },
    { label: "Oceanography", state: oceanographyOn ? marine.layers.oceanography.state : "not-enabled" },
    { label: "Chlorophyll", state: marine.enabled.chlorophyll ? marine.layers.chlorophyll.state : "not-enabled" },
    { label: "PFZ", state: "static-unavailable" },
  ];

  const layerError =
    (marine.enabled.risk && marine.layers.riskSurface.state.kind === "error" && marine.layers.riskSurface.state.message) ||
    (marine.enabled.geofences && marine.layers.geofences.state.kind === "error" && marine.layers.geofences.state.message) ||
    (marine.enabled.suitability && marine.layers.suitability.state.kind === "error" && marine.layers.suitability.state.message) ||
    (oceanographyOn && marine.layers.oceanography.state.kind === "error" && marine.layers.oceanography.state.message) ||
    (marine.enabled.chlorophyll && marine.layers.chlorophyll.state.kind === "error" && marine.layers.chlorophyll.state.message) ||
    null;

  return (
    <main className="min-h-screen bg-marine-surface-alt pt-20">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-10 sm:px-10 lg:flex-row lg:gap-10 lg:px-16 lg:py-14">
        <section className="flex-shrink-0 lg:w-[380px]">
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">Deterministic Routing</p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-marine-ink sm:text-4xl">Plan a route.</h1>
          <p className="mt-4 text-base leading-relaxed text-marine-ink-muted">
            Risk-aware routing over the Mangaluru–Udupi demo region, backed by real live environmental sampling —
            avoids restricted zones and weighs live risk, never a straight line pretending to be one. To explore
            marine conditions across the whole region, visit the{" "}
            <a href="/marine-map" className="text-marine-blue underline hover:text-marine-cyan">
              Marine Intelligence Map
            </a>
            .
          </p>

          <div className="mt-8 rounded-2xl border border-marine-border bg-marine-surface p-5 shadow-sm sm:p-6">
            <RoutePlanner onStateChange={handleStateChange} />
          </div>
        </section>

        <section className="relative min-h-[420px] flex-1 overflow-hidden rounded-2xl border border-marine-border lg:min-h-[720px]">
          <RouteMap
            origin={mapState.origin}
            destination={mapState.destination}
            routeCoordinates={selectedRoute?.path_coordinates ?? null}
            reducedMotion={reducedMotion}
            className="h-full w-full"
            deckLayers={deckLayers}
          />

          <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-3">
            <LayerControlPanel groups={layerGroups} enabled={marine.enabled} onToggle={(k) => marine.toggleLayer(k as never)} onRefresh={marine.refresh} refreshing={marine.refreshing} />
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
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg border border-marine-warning/50 bg-marine-surface px-4 py-2 text-xs font-medium text-[#92600A] shadow-lg">
              Bathymetry — DATA INTEGRATION NOT CURRENTLY AVAILABLE ({marine.layers.bathymetry.state.reason})
            </div>
          )}

          {marine.enabled.chlorophyll && marine.layers.chlorophyll.state.kind === "unavailable" && (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg border border-marine-warning/50 bg-marine-surface px-4 py-2 text-xs font-medium text-[#92600A] shadow-lg">
              Chlorophyll — DATA INTEGRATION NOT CURRENTLY AVAILABLE ({marine.layers.chlorophyll.state.reason})
            </div>
          )}

          {layerError && (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg border border-marine-danger/40 bg-marine-surface px-4 py-2 text-xs font-medium text-marine-danger shadow-lg">
              {layerError}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
