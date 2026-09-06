import { useEffect, useMemo, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";

import {
  buildBathymetryLayer,
  buildChlorophyllLayer,
  buildCurrentsLayer,
  buildGeofenceLayer,
  buildIncoisSstLayer,
  buildRiskSurfaceLayer,
  buildSstLayer,
  buildSuitabilityLayer,
  buildWavesLayer,
  buildWindLayer,
  type SelectedFeature,
} from "../components/map/mapLayers";
import { useMapLayer, type MapLayerState } from "./useMapLayer";
import {
  getBathymetryLayer,
  getChlorophyllLayer,
  getGeofencesLayer,
  getOceanographyLayer,
  getRiskSurfaceLayer,
  getSuitabilityLayer,
  type BathymetryLayerMeta,
  type ChlorophyllLayerMeta,
  type GeofencesLayerMeta,
  type IncoisSstLayerMeta,
  type OceanographyApiResponse,
  type OceanographyLayerMeta,
  type RiskSurfaceLayerMeta,
  type SuitabilityLayerMeta,
} from "../lib/api";

export type MarineLayerKey =
  | "bathymetry"
  | "risk"
  | "geofences"
  | "suitability"
  | "sst"
  | "incoisSst"
  | "currents"
  | "waves"
  | "wind"
  | "chlorophyll";

/**
 * The shared set of ORCA environmental/intelligence layers used by BOTH
 * the Route Planner and the Marine Intelligence Map — one fetch/toggle/
 * deck.gl-build implementation, not two. Route-specific rendering (the
 * route line and route-risk segments) stays with whichever page actually
 * has route state; this hook only ever fetches and renders layers backed
 * by `GET /api/v1/layers/*`.
 */
export function useMarineLayers(defaultEnabled: Partial<Record<MarineLayerKey, boolean>> = {}, at?: string) {
  const [enabled, setEnabled] = useState<Record<MarineLayerKey, boolean>>({
    bathymetry: false,
    risk: false,
    geofences: false,
    suitability: false,
    sst: false,
    incoisSst: false,
    currents: false,
    waves: false,
    wind: false,
    chlorophyll: false,
    ...defaultEnabled,
  });
  const [selected, setSelected] = useState<SelectedFeature | null>(null);

  // Bathymetry/geofences/chlorophyll have no time dimension (static
  // reference / no source-exposed history — see their own endpoint docs)
  // and never take `at`. Risk, oceanography (SST/currents/waves/wind), and
  // suitability DO — moving the time slider re-requests real backend data
  // for the newly-selected hour, never just relabels the same response.
  const bathymetry = useMapLayer<BathymetryLayerMeta>(enabled.bathymetry, getBathymetryLayer);
  const chlorophyll = useMapLayer<ChlorophyllLayerMeta>(enabled.chlorophyll, getChlorophyllLayer);
  const riskSurface = useMapLayer<RiskSurfaceLayerMeta>(enabled.risk, () => getRiskSurfaceLayer({ at }));
  const geofences = useMapLayer<GeofencesLayerMeta>(enabled.geofences, getGeofencesLayer);
  const suitability = useMapLayer<SuitabilityLayerMeta>(enabled.suitability, () => getSuitabilityLayer({ at }));
  // SST, currents, waves, wind, and INCOIS SST's "is it acquired" check are
  // all views over the SAME oceanography fetch (real Open-Meteo samples +
  // the extended incois_sst block, backend/app/api/v1/layers.py) — one
  // request backs five toggles, never five separate requests.
  const oceanographyEnabled = enabled.sst || enabled.currents || enabled.waves || enabled.wind || enabled.incoisSst;
  const oceanography = useMapLayer<OceanographyLayerMeta, OceanographyApiResponse>(oceanographyEnabled, () => getOceanographyLayer({ at }));

  // Re-fetch the three time-varying layers when the selected timestamp
  // changes (and they are already showing data) — the actual mechanism
  // behind the time slider's "selected timestamp maps to real backend
  // data" requirement. Skipped on mount (nothing to re-fetch yet; the
  // initial `at` is picked up by useMapLayer's own first fetch).
  const previousAt = useRef(at);
  useEffect(() => {
    if (previousAt.current === at) return;
    previousAt.current = at;
    if (enabled.risk && riskSurface.state.kind !== "idle") riskSurface.refresh();
    if (oceanographyEnabled && oceanography.state.kind !== "idle") oceanography.refresh();
    if (enabled.suitability && suitability.state.kind !== "idle") suitability.refresh();
  }, [at, enabled.risk, enabled.suitability, oceanographyEnabled, oceanography, riskSurface, suitability]);

  const toggleLayer = (key: MarineLayerKey) => setEnabled((prev) => ({ ...prev, [key]: !prev[key] }));

  const refresh = () => {
    if (enabled.bathymetry) bathymetry.refresh();
    if (enabled.chlorophyll) chlorophyll.refresh();
    if (enabled.risk) riskSurface.refresh();
    if (enabled.geofences) geofences.refresh();
    if (enabled.suitability) suitability.refresh();
    if (oceanographyEnabled) oceanography.refresh();
  };
  const refreshing =
    riskSurface.state.kind === "loading" ||
    geofences.state.kind === "loading" ||
    suitability.state.kind === "loading" ||
    oceanography.state.kind === "loading" ||
    bathymetry.state.kind === "loading" ||
    chlorophyll.state.kind === "loading";

  // INCOIS SST rides on the oceanography response's own `raw.incois_sst`
  // sub-object (backend/app/api/v1/layers.py's `_incois_sst_block`) —
  // derived here into its own MapLayerState-shaped value so callers (the
  // layer control, data-status panel) can treat it exactly like any other
  // layer, without a second network request.
  const incoisSstState: MapLayerState<IncoisSstLayerMeta> = useMemo(() => {
    if (oceanography.state.kind !== "loaded") return oceanography.state as MapLayerState<IncoisSstLayerMeta>;
    const block = oceanography.state.raw.incois_sst;
    if (!block.data) return { kind: "unavailable", meta: block.meta, reason: block.meta?.reason ?? "Data unavailable." };
    return { kind: "loaded", data: block.data, meta: block.meta as IncoisSstLayerMeta, raw: block };
  }, [oceanography.state]);

  const deckLayers: Layer[] = useMemo(() => {
    const layers: Layer[] = [];
    if (enabled.bathymetry && bathymetry.state.kind === "loaded") layers.push(buildBathymetryLayer(bathymetry.state.data, setSelected));
    if (enabled.risk && riskSurface.state.kind === "loaded") layers.push(buildRiskSurfaceLayer(riskSurface.state.data, setSelected));
    if (enabled.geofences && geofences.state.kind === "loaded") layers.push(buildGeofenceLayer(geofences.state.data, setSelected));
    if (enabled.suitability && suitability.state.kind === "loaded") layers.push(buildSuitabilityLayer(suitability.state.data, setSelected));
    if (enabled.sst && oceanography.state.kind === "loaded") layers.push(buildSstLayer(oceanography.state.data, setSelected));
    if (enabled.waves && oceanography.state.kind === "loaded") layers.push(buildWavesLayer(oceanography.state.data, setSelected));
    if (enabled.currents && oceanography.state.kind === "loaded") layers.push(buildCurrentsLayer(oceanography.state.data, setSelected));
    if (enabled.wind && oceanography.state.kind === "loaded") layers.push(buildWindLayer(oceanography.state.data, setSelected));
    if (enabled.chlorophyll && chlorophyll.state.kind === "loaded") layers.push(buildChlorophyllLayer(chlorophyll.state.data, setSelected));
    if (enabled.incoisSst && incoisSstState.kind === "loaded") layers.push(buildIncoisSstLayer(incoisSstState.data, setSelected));
    return layers;
  }, [enabled, bathymetry.state, riskSurface.state, geofences.state, suitability.state, oceanography.state, chlorophyll.state, incoisSstState]);

  return {
    enabled,
    toggleLayer,
    deckLayers,
    selected,
    setSelected,
    refresh,
    refreshing,
    layers: { bathymetry, chlorophyll, riskSurface, geofences, suitability, oceanography },
    incoisSstState,
  };
}
