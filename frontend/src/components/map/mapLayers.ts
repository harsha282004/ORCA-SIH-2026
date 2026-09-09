// deck.gl layer factories for the Marine Intelligence Map. Every function
// here is a PURE rendering transform: it takes GeoJSON already computed by
// an ORCA backend engine (app/api/v1/layers.py) and turns it into a deck.gl
// layer instance. Nothing in this file calculates risk, suitability,
// geofence membership, or a route — colors/sizes are presentation only,
// derived from fields the backend already attached.
import { GeoJsonLayer, ScatterplotLayer, PathLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { PickingInfo } from "@deck.gl/core";

import type { GeoJsonFeatureCollection, RouteCellRef, RouteResultData } from "../../lib/api";

export type SelectedFeature = { layer: string; properties: Record<string, unknown> };

const COLOR = {
  success: [16, 185, 129] as [number, number, number],
  warning: [245, 158, 11] as [number, number, number],
  danger: [239, 68, 68] as [number, number, number],
  cyan: [56, 189, 248] as [number, number, number],
  cyanLight: [125, 211, 252] as [number, number, number],
  sand: [212, 165, 116] as [number, number, number],
  gray: [100, 116, 139] as [number, number, number],
};

// --- Risk surface (Layer 2 — must-have) -----------------------------------

const RISK_COLORS: Record<string, [number, number, number]> = {
  LOW: COLOR.success,
  MODERATE: COLOR.warning,
  HIGH: COLOR.danger,
};

export function buildRiskSurfaceLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new GeoJsonLayer({
    id: "orca-risk-surface",
    data: data as unknown as GeoJSON.FeatureCollection,
    pickable: true,
    stroked: true,
    filled: true,
    // Kept translucent and thin-stroked on purpose: at the routing engine's
    // 3km grid resolution the demo bbox has ~1,600 adjacent cells, dense
    // enough that a bolder fill/stroke turns into a solid wash that hides
    // the basemap's real coastline/place-name context underneath — this
    // task's own "prioritize map readability... never a map with numbers
    // printed over it" requirement, not a cosmetic preference.
    getFillColor: (f: { properties: Record<string, unknown> }) => {
      if (!f.properties.navigable) return [71, 85, 105, 30]; // blocked cell — muted, geofence layer explains why
      const level = f.properties.risk_level as string | undefined;
      const [r, g, b] = RISK_COLORS[level ?? "LOW"] ?? COLOR.gray;
      return [r, g, b, 55];
    },
    getLineColor: (f: { properties: Record<string, unknown> }) => {
      if (!f.properties.navigable) return [71, 85, 105, 50];
      const level = f.properties.risk_level as string | undefined;
      const [r, g, b] = RISK_COLORS[level ?? "LOW"] ?? COLOR.gray;
      return [r, g, b, 90];
    },
    lineWidthMinPixels: 0.5,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "risk-surface", properties: info.object.properties });
    },
    updateTriggers: { getFillColor: [data], getLineColor: [data] },
  });
}

// --- Geofences / restricted zones (Layer 3 — must-have) --------------------

export function buildGeofenceLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new GeoJsonLayer({
    id: "orca-geofences",
    data: data as unknown as GeoJSON.FeatureCollection,
    pickable: true,
    stroked: true,
    filled: true,
    getFillColor: [239, 68, 68, 70],
    getLineColor: [239, 68, 68, 220],
    lineWidthMinPixels: 2,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "geofences", properties: info.object.properties });
    },
  });
}

// --- ORCA Fishing Suitability (Layer 5 — must-have) -------------------------

const SUITABILITY_COLORS: Record<string, [number, number, number]> = {
  HIGH: COLOR.success,
  MODERATE: COLOR.cyanLight,
  LOW: COLOR.warning,
  NOT_RECOMMENDED: COLOR.gray,
};

export function buildSuitabilityLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-suitability",
    data: data.features,
    pickable: true,
    radiusMinPixels: 6,
    radiusMaxPixels: 16,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: 350,
    getFillColor: (f: { properties: Record<string, unknown> }) => {
      const [r, g, b] = SUITABILITY_COLORS[(f.properties.category as string) ?? ""] ?? COLOR.gray;
      return [r, g, b, 210];
    },
    getLineColor: [10, 37, 64, 200],
    lineWidthMinPixels: 1,
    stroked: true,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "suitability", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- SST (Layer 6) -----------------------------------------------------------

/** Simple blue (cool) -> amber (warm) gradient over a plausible tropical
 * coastal SST range — presentation only, the underlying value is real. */
function sstColor(tempC: number | null | undefined): [number, number, number, number] {
  if (tempC == null) return [...COLOR.gray, 150];
  const t = Math.max(0, Math.min(1, (tempC - 24) / (32 - 24)));
  const r = Math.round(56 + t * (245 - 56));
  const g = Math.round(189 + t * (158 - 189));
  const b = Math.round(248 + t * (11 - 248));
  return [r, g, b, 200];
}

export function buildSstLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-sst",
    data: data.features,
    pickable: true,
    radiusMinPixels: 10,
    radiusMaxPixels: 22,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: 500,
    getFillColor: (f: { properties: Record<string, unknown> }) => sstColor(f.properties.sea_surface_temperature_c as number | null),
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "sst", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Waves (Layer 9) ---------------------------------------------------------

export function buildWavesLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-waves",
    data: data.features,
    pickable: true,
    radiusMinPixels: 4,
    radiusMaxPixels: 20,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: (f: { properties: Record<string, unknown> }) => 300 + ((f.properties.wave_height_m as number) || 0) * 600,
    getFillColor: [30, 111, 168, 160],
    getLineColor: [125, 211, 252, 220],
    lineWidthMinPixels: 1,
    stroked: true,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "waves", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Ocean currents (Layer 8) -------------------------------------------------
//
// Rendered as a short direction indicator (a 2-point path from the sample
// site, rotated toward `ocean_current_direction_deg`) whose length scales
// with `ocean_current_velocity_ms` — a schematic vector, not a to-map-scale
// distance (documented in the legend). No vector is invented: direction and
// speed both come straight from the real Open-Meteo Marine sample.

function destinationPoint(lon: number, lat: number, bearingDeg: number, lengthDeg: number): [number, number] {
  const rad = (bearingDeg * Math.PI) / 180;
  // Meteorological "direction" is where the current comes FROM; adding 180°
  // points the indicator the direction the water actually moves TOWARD.
  const travelRad = rad + Math.PI;
  return [lon + lengthDeg * Math.sin(travelRad), lat + lengthDeg * Math.cos(travelRad)];
}

// --- Bathymetry (Layer 1 — real GEBCO depth samples) ------------------------

/** Blue gradient, deep = darker — shallow (near 0m) is light, deep (beyond
 * ~1500m, the deepest this bbox's samples reach) is near-black-blue. */
function depthColor(depthM: number | null | undefined): [number, number, number, number] {
  if (depthM == null) return [...COLOR.gray, 150];
  const depth = Math.max(0, -depthM); // GEBCO convention: negative = below sea level
  const t = Math.min(1, depth / 1500);
  const r = Math.round(125 - t * 110);
  const g = Math.round(211 - t * 180);
  const b = Math.round(252 - t * 100);
  return [r, g, b, 190];
}

export function buildBathymetryLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-bathymetry",
    data: data.features,
    pickable: true,
    radiusMinPixels: 5,
    radiusMaxPixels: 14,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: 400,
    getFillColor: (f: { properties: Record<string, unknown> }) => depthColor(f.properties.depth_m as number | null),
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "bathymetry", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Chlorophyll (Layer 7 — real INCOIS chlorophyll samples) ----------------

/** Green intensity gradient — low chlorophyll is pale, high is deep green,
 * matching conventional ocean-colour cartography. */
function chlorophyllColor(value: number | null | undefined): [number, number, number, number] {
  if (value == null) return [...COLOR.gray, 150];
  const t = Math.min(1, value / 3); // most of this bbox's samples fall under ~3 mg/m^3
  const r = Math.round(240 - t * 210);
  const g = Math.round(240 - t * 90);
  const b = Math.round(200 - t * 190);
  return [r, g, b, 200];
}

export function buildChlorophyllLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-chlorophyll",
    data: data.features,
    pickable: true,
    radiusMinPixels: 8,
    radiusMaxPixels: 20,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: 600,
    getFillColor: (f: { properties: Record<string, unknown> }) => chlorophyllColor(f.properties.value as number | null),
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "chlorophyll", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Route risk (Route Risk Visualization — must-have) ------------------
//
// Colors each already-computed route segment by the SAME `risk_score`
// app.routing.costs.compute_edge_cost used to cost that segment
// (RouteCellRef.risk_score, from backend/app/routing/models.py) — never a
// second risk calculation. `path_cells[i+1].risk_score` matches
// `to_node.risk_score` in the backend's own edge-cost formula exactly.

function riskLevelFromScore(score: number | null): "LOW" | "MODERATE" | "HIGH" {
  if (score === null) return "LOW";
  if (score >= 0.66) return "HIGH";
  if (score >= 0.33) return "MODERATE";
  return "LOW";
}

export function buildRouteRiskLayer(pathCells: RouteCellRef[], onClick: (f: SelectedFeature) => void) {
  const segments = [];
  for (let i = 0; i < pathCells.length - 1; i++) {
    const from = pathCells[i];
    const to = pathCells[i + 1];
    segments.push({
      path: [
        [from.longitude, from.latitude],
        [to.longitude, to.latitude],
      ],
      properties: to,
    });
  }

  return new PathLayer({
    id: "orca-route-risk",
    data: segments,
    pickable: true,
    widthMinPixels: 5,
    getPath: (d: { path: [number, number][] }) => d.path,
    getColor: (d: { properties: RouteCellRef }) => {
      const [r, g, b] = RISK_COLORS[riskLevelFromScore(d.properties.risk_score)] ?? COLOR.cyan;
      return [r, g, b, 230];
    },
    getWidth: 5,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "route", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
    updateTriggers: { getColor: [pathCells] },
  });
}

// --- INCOIS SST (Phase 2, Part A1 — real acquired samples, distinct from Open-Meteo SST) ---
//
// Rendered with a visibly different marker style (hollow ring, violet)
// from `buildSstLayer`'s filled circles — the two are different providers,
// different sample densities, and must never be visually confused as one
// continuous SST field.

function incoisSstColor(tempC: number | null | undefined): [number, number, number, number] {
  if (tempC == null) return [...COLOR.gray, 150];
  const t = Math.max(0, Math.min(1, (tempC - 28) / (32 - 28)));
  const r = Math.round(167 + t * (245 - 167));
  const g = Math.round(139 + t * (158 - 139));
  const b = Math.round(250 + t * (11 - 250));
  return [r, g, b, 220];
}

export function buildIncoisSstLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-incois-sst",
    data: data.features,
    pickable: true,
    stroked: true,
    filled: false,
    radiusMinPixels: 9,
    radiusMaxPixels: 20,
    lineWidthMinPixels: 2,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: 550,
    getLineColor: (f: { properties: Record<string, unknown> }) => incoisSstColor(f.properties.value as number | null),
    getLineWidth: 2,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "incois-sst", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Wind (Phase 2 §9 — real Open-Meteo wind, same sample sites as oceanography) ---

export function buildWindLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  const paths = data.features
    .filter((f) => typeof f.properties.wind_speed_ms === "number")
    .map((f) => {
      const [lon, lat] = f.geometry.coordinates as [number, number];
      const speed = (f.properties.wind_speed_ms as number) || 0;
      const direction = (f.properties.wind_direction_deg as number) || 0;
      const length = 0.015 + Math.min(speed, 15) * 0.004;
      return { path: [[lon, lat], destinationPoint(lon, lat, direction, length)], properties: f.properties };
    });

  return new PathLayer({
    id: "orca-wind",
    data: paths,
    pickable: true,
    widthMinPixels: 1.5,
    getPath: (d: { path: [number, number][] }) => d.path,
    getColor: [226, 232, 240, 200],
    getWidth: 1.5,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "wind", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Fishing candidates (Phase 3 — ranked/avoid, visually distinct from ---
// --- both ORCA Risk and ORCA Fishing Suitability's own map-layer style) ---

const FISHING_CANDIDATE_COLORS: Record<string, [number, number, number]> = {
  ranked: COLOR.success,
  avoid: COLOR.danger,
  insufficient_data: COLOR.gray,
};

export function buildFishingCandidatesLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-fishing-candidates",
    data: data.features,
    pickable: true,
    stroked: true,
    radiusMinPixels: 7,
    radiusMaxPixels: 22,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    // Ranked candidates scale by rank (1 = biggest, most prominent); avoid/insufficient stay a fixed small size.
    getRadius: (f: { properties: Record<string, unknown> }) => {
      const rank = f.properties.rank as number | null;
      if (f.properties.status === "ranked" && rank) return Math.max(350, 900 - rank * 15);
      return 300;
    },
    getFillColor: (f: { properties: Record<string, unknown> }) => {
      const [r, g, b] = FISHING_CANDIDATE_COLORS[(f.properties.status as string) ?? ""] ?? COLOR.gray;
      return [r, g, b, f.properties.status === "ranked" ? 210 : 130];
    },
    getLineColor: [10, 37, 64, 220],
    lineWidthMinPixels: 1,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "fishing-candidate", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}

// --- Marine hazards (Phase 4 — GET /api/v1/safety/hazards) ------------------
//
// Visually distinct from every other layer: a hollow, thick-ringed marker
// (never confused with the filled Fishing Candidate / SST dots), colored by
// real HazardSeverity, sized by severity so a CRITICAL cyclone reads as
// unmistakably more urgent than an ADVISORY-band wave reading. A hazard
// with no point geometry (none currently exist) is filtered out upstream —
// this layer never invents a location for one.

const HAZARD_SEVERITY_COLORS: Record<string, [number, number, number]> = {
  INFO: COLOR.gray,
  ADVISORY: [250, 204, 21], // amber
  WARNING: COLOR.warning,
  DANGER: COLOR.danger,
  CRITICAL: [190, 24, 93], // deep magenta-red — visually the most alarming tier
};

const HAZARD_SEVERITY_RADIUS: Record<string, number> = {
  INFO: 500,
  ADVISORY: 800,
  WARNING: 1100,
  DANGER: 1500,
  CRITICAL: 2200,
};

export function buildHazardsLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  return new ScatterplotLayer({
    id: "orca-hazards",
    data: data.features,
    pickable: true,
    stroked: true,
    filled: true,
    radiusMinPixels: 10,
    radiusMaxPixels: 45,
    getPosition: (f: { geometry: { coordinates: [number, number] } }) => f.geometry.coordinates,
    getRadius: (f: { properties: Record<string, unknown> }) => HAZARD_SEVERITY_RADIUS[(f.properties.severity as string) ?? ""] ?? 700,
    getFillColor: (f: { properties: Record<string, unknown> }) => {
      const [r, g, b] = HAZARD_SEVERITY_COLORS[(f.properties.severity as string) ?? ""] ?? COLOR.gray;
      return [r, g, b, 60];
    },
    getLineColor: (f: { properties: Record<string, unknown> }) => {
      const [r, g, b] = HAZARD_SEVERITY_COLORS[(f.properties.severity as string) ?? ""] ?? COLOR.gray;
      return [r, g, b, 255];
    },
    lineWidthMinPixels: 3,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "hazard", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
    updateTriggers: { getFillColor: [data], getLineColor: [data], getRadius: [data] },
  });
}

// --- Route alternatives (Phase 5 — task §12/§25) ---------------------------
//
// Renders every NON-selected route option as a distinctly-styled path
// (never confused with the selected route's own segment-risk-colored
// PathLayer, `buildRouteRiskLayer` above, or the RouteMap's own animated
// `routeCoordinates` draw-in) so a user can visually tell SELECTED ROUTE
// apart from ALTERNATIVE ROUTES and BLOCKED ROUTES at a glance — the
// task's own explicit visual-distinctness requirement (§25).

export function buildAlternativeRoutesLayer(
  routes: RouteResultData[],
  selectedLabel: string | null,
  onClick: (f: SelectedFeature) => void,
) {
  const others = routes.filter((r) => r.label !== selectedLabel);
  return new PathLayer({
    id: "orca-route-alternatives",
    data: others,
    pickable: true,
    widthMinPixels: 3,
    getPath: (r: RouteResultData) => r.path_coordinates.map((c): [number, number] => [c.longitude, c.latitude]),
    getColor: (r: RouteResultData) =>
      r.decision.outcome === "NO_SAFE_RECOMMENDATION" ? [239, 68, 68, 160] : [148, 163, 184, 170], // blocked=red, otherwise muted slate
    getWidth: 3,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "route-option", properties: info.object as unknown as Record<string, unknown> });
    },
  });
}

// --- Real spatial heatmap (Phase 12) ----------------------------------------
//
// Built ONLY from the same real, already-fetched multi-point GeoJSON every
// other layer in this file uses (the oceanography 4x4 grid, the risk/
// suitability grid, the acquired chlorophyll samples) — never a second
// data source, never a fabricated point. `HeatmapLayer` (deck.gl's own
// kernel-density aggregation) visually interpolates BETWEEN real sample
// points for a continuous-looking surface; it never invents a value AT a
// point that wasn't sampled — the underlying weighted points are always
// the genuine per-feature values. A feature collection with zero features
// (or every point missing the requested variable) yields `null` here, not
// an empty-looking-but-still-fabricated heatmap.

export type HeatmapVariable = "wave_height" | "wind_speed" | "sst" | "risk" | "suitability" | "chlorophyll";

/** Point geometries use their own coordinates; polygon grid cells (the risk
 * surface) use their real vertex centroid — a presentation-only geometric
 * derivation from the polygon's own true boundary, never an invented
 * location. */
function featureLngLat(feature: { geometry: { type: string; coordinates: unknown } }): [number, number] | null {
  const geom = feature.geometry;
  if (geom.type === "Point") return geom.coordinates as [number, number];
  if (geom.type === "Polygon") {
    const ring = (geom.coordinates as [number, number][][])[0];
    if (!ring || ring.length === 0) return null;
    const lon = ring.reduce((sum, [x]) => sum + x, 0) / ring.length;
    const lat = ring.reduce((sum, [, y]) => sum + y, 0) / ring.length;
    return [lon, lat];
  }
  return null;
}

const HEATMAP_VALUE_FIELD: Record<HeatmapVariable, (props: Record<string, unknown>) => number | null> = {
  wave_height: (p) => (typeof p.wave_height_m === "number" ? p.wave_height_m : null),
  wind_speed: (p) => (typeof p.wind_speed_ms === "number" ? p.wind_speed_ms : null),
  sst: (p) => (typeof p.sea_surface_temperature_c === "number" ? p.sea_surface_temperature_c : null),
  risk: (p) => (p.navigable === false ? null : typeof p.risk_score === "number" ? p.risk_score : null),
  suitability: (p) => (typeof p.score === "number" ? p.score : null),
  chlorophyll: (p) => (typeof p.value === "number" ? p.value : null),
};

const HEATMAP_COLOR_RANGE: Record<HeatmapVariable, [number, number, number][]> = {
  // Marine (wave/wind/SST): cool blue -> cyan -> warm, per task's own
  // "professional marine visualization" palette guidance — never a rainbow.
  wave_height: [
    [15, 58, 95],
    [30, 111, 168],
    [56, 189, 248],
    [125, 211, 252],
    [212, 165, 116],
  ],
  wind_speed: [
    [15, 58, 95],
    [30, 111, 168],
    [56, 189, 248],
    [125, 211, 252],
    [212, 165, 116],
  ],
  sst: [
    [15, 58, 95],
    [56, 189, 248],
    [125, 211, 252],
    [245, 158, 11],
  ],
  // Risk / suitability: green -> yellow -> orange -> red, matching the
  // rest of the app's own semantic risk coloring — never a novel palette.
  risk: [
    [16, 185, 129],
    [245, 158, 11],
    [239, 68, 68],
  ],
  suitability: [
    [100, 116, 139],
    [245, 158, 11],
    [125, 211, 252],
    [16, 185, 129],
  ],
  chlorophyll: [
    [240, 240, 200],
    [125, 180, 90],
    [30, 90, 16],
  ],
};

export function buildHeatmapLayer(data: GeoJsonFeatureCollection, variable: HeatmapVariable) {
  const getValue = HEATMAP_VALUE_FIELD[variable];
  const points = data.features
    .map((f) => {
      const pos = featureLngLat(f as unknown as { geometry: { type: string; coordinates: unknown } });
      const value = getValue(f.properties);
      if (!pos || value == null) return null;
      return { position: pos, weight: Math.max(value, 0.0001) };
    })
    .filter((p): p is { position: [number, number]; weight: number } => p !== null);

  // Never render a heatmap from zero real points — an honest empty layer
  // (the UI shows "HEATMAP UNAVAILABLE" in this case; see MarineMapPage).
  if (points.length === 0) return null;

  return new HeatmapLayer({
    id: `orca-heatmap-${variable}`,
    data: points,
    pickable: false,
    getPosition: (d: { position: [number, number] }) => d.position,
    getWeight: (d: { weight: number }) => d.weight,
    radiusPixels: 60,
    intensity: 1,
    threshold: 0.03,
    colorRange: HEATMAP_COLOR_RANGE[variable].map(([r, g, b]) => [r, g, b, 255]) as [number, number, number, number][],
  });
}

/** Real min/max of whatever is actually loaded — the heatmap legend's own
 * range, never a fixed/invented scale (task §"Legend": "Use actual data
 * ranges... Do not choose ranges simply to make colors look dramatic"). */
export function heatmapValueExtent(data: GeoJsonFeatureCollection, variable: HeatmapVariable): { min: number; max: number } | null {
  const getValue = HEATMAP_VALUE_FIELD[variable];
  const values = data.features.map((f) => getValue(f.properties)).filter((v): v is number => v != null);
  if (values.length === 0) return null;
  return { min: Math.min(...values), max: Math.max(...values) };
}

export function buildCurrentsLayer(data: GeoJsonFeatureCollection, onClick: (f: SelectedFeature) => void) {
  const paths = data.features.map((f) => {
    const [lon, lat] = f.geometry.coordinates as [number, number];
    const velocity = (f.properties.ocean_current_velocity_ms as number) || 0;
    const direction = (f.properties.ocean_current_direction_deg as number) || 0;
    const length = 0.02 + Math.min(velocity, 1.5) * 0.05;
    return { path: [[lon, lat], destinationPoint(lon, lat, direction, length)], properties: f.properties };
  });

  return new PathLayer({
    id: "orca-currents",
    data: paths,
    pickable: true,
    widthMinPixels: 2,
    getPath: (d: { path: [number, number][] }) => d.path,
    getColor: [125, 211, 252, 220],
    getWidth: 2,
    onClick: (info: PickingInfo) => {
      if (info.object) onClick({ layer: "currents", properties: (info.object as { properties: Record<string, unknown> }).properties });
    },
  });
}
