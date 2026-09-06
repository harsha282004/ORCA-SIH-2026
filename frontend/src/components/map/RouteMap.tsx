import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";

import type { Coordinate } from "../../lib/api";

// The demo region's own bounding box — Mangaluru-Udupi coastal Karnataka —
// reused verbatim from backend/app/config.py's DEMO_BBOX_* defaults
// (also documented in docs/demo_region.md). Never invented: this is the
// exact box every backend routing/geofence/risk computation is already
// scoped to, so the map's initial framing matches the region the backend
// can actually answer questions about.
const DEMO_BBOX = {
  minLat: 12.7,
  minLon: 73.5,
  maxLat: 13.45,
  maxLon: 75.05,
};

// A free, no-API-key raster basemap. CARTO's classic anonymous basemap
// tiles (both the commonly-referenced "dark_matter" path AND its current
// "dark_all" path) were tried and verified LIVE during this task's QA:
// "dark_matter" 404s outright; "dark_all" returns 200 but every tile is
// now watermarked "API KEY REQUIRED — carto.com/basemaps/apikey" — CARTO
// has since restricted anonymous basemap access, and this project has no
// CARTO account/key to add (nor should one be invented). OpenStreetMap's
// own tile server (no key, no account, the same source data CARTO's own
// basemaps are built from) was verified to return real, unwatermarked
// tiles and is used instead. Its default cartography is light, not dark —
// `.orca-map-dark-tiles` below (index.css) applies the standard, widely-
// used invert+hue-rotate CSS trick to approximate a dark map from it,
// scoped to the tile canvas only so markers/route-line colors are
// untouched.
const BASEMAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    "osm-raster": {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm-raster-layer", type: "raster", source: "osm-raster", minzoom: 0, maxzoom: 20 }],
};

const ROUTE_SOURCE_ID = "orca-route-line";
const ROUTE_LAYER_ID = "orca-route-line-layer";

function toLngLat(coord: Coordinate): [number, number] {
  return [coord.longitude, coord.latitude];
}

interface RouteMapProps {
  origin: Coordinate;
  destination: Coordinate;
  /** The actual computed route geometry from a completed POST /api/v1/route response — never computed here. */
  routeCoordinates: Coordinate[] | null;
  reducedMotion: boolean;
  className?: string;
  /** Pre-built deck.gl layer instances (risk surface, geofences, suitability,
   * oceanography, route-risk, …) — RouteMap only mounts the deck.gl overlay
   * and hands it whatever layers the caller currently has enabled; it never
   * decides which layers exist or what they contain. */
  deckLayers?: Layer[];
}

/**
 * A real, interactive MapLibre GL map centered on the Mangaluru-Udupi
 * coastal demo region — pannable, zoomable, and able to render the
 * ACTUAL route geometry a completed `/api/v1/route` response returns, plus
 * any number of deck.gl-rendered ORCA intelligence layers on top (risk
 * surface, geofences, fishing suitability, oceanography). This component
 * never computes a route, a distance, or a risk value itself; it only
 * visualizes what the backend already returned.
 */
export function RouteMap({ origin, destination, routeCoordinates, reducedMotion, className, deckLayers }: RouteMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const originMarkerRef = useRef<maplibregl.Marker | null>(null);
  const destinationMarkerRef = useRef<maplibregl.Marker | null>(null);

  // --- Map initialization (once) ------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const map = new maplibregl.Map({
      container,
      style: BASEMAP_STYLE,
      center: [(DEMO_BBOX.minLon + DEMO_BBOX.maxLon) / 2, (DEMO_BBOX.minLat + DEMO_BBOX.maxLat) / 2],
      zoom: 9,
      attributionControl: false, // added explicitly below, compact, to keep the map uncluttered
    });
    mapRef.current = map;

    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const overlay = new MapboxOverlay({ layers: [] });
    map.addControl(overlay as unknown as maplibregl.IControl);
    overlayRef.current = overlay;

    map.on("load", () => {
      // Frame the whole demo region on first load — close enough that
      // Mangaluru's coastline and the surrounding Arabian Sea are both
      // legible, never so tight that maritime context disappears.
      map.fitBounds(
        [
          [DEMO_BBOX.minLon, DEMO_BBOX.minLat],
          [DEMO_BBOX.maxLon, DEMO_BBOX.maxLat],
        ],
        { padding: 48, animate: false },
      );

      map.addSource(ROUTE_SOURCE_ID, {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [] } },
      });
      map.addLayer({
        id: ROUTE_LAYER_ID,
        type: "line",
        source: ROUTE_SOURCE_ID,
        layout: { "line-join": "round", "line-cap": "round" },
        // Rendered underneath deck.gl's own risk-colored route segments
        // (see the route-risk effect below) — this plain line is only the
        // visible fallback for a zero-length (single-cell) route, where
        // there is no second cell to color a segment between.
        paint: { "line-color": "#38BDF8", "line-width": 3, "line-opacity": 0.6 },
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
    // Intentionally initialized once — origin/destination/route updates are
    // handled by the effects below via the stable mapRef, not by
    // re-creating the map itself.
  }, []);

  // --- deck.gl layers (risk surface, geofences, suitability, oceanography, route-risk) ---
  useEffect(() => {
    overlayRef.current?.setProps({ layers: deckLayers ?? [] });
  }, [deckLayers]);

  // --- Origin / destination markers ---------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyMarkers = () => {
      if (!originMarkerRef.current) {
        originMarkerRef.current = new maplibregl.Marker({ color: "#38BDF8" }).setLngLat(toLngLat(origin)).addTo(map);
      } else {
        originMarkerRef.current.setLngLat(toLngLat(origin));
      }
      if (!destinationMarkerRef.current) {
        destinationMarkerRef.current = new maplibregl.Marker({ color: "#D4A574" }).setLngLat(toLngLat(destination)).addTo(map);
      } else {
        destinationMarkerRef.current.setLngLat(toLngLat(destination));
      }
    };

    if (map.loaded()) applyMarkers();
    else map.once("load", applyMarkers);
  }, [origin, destination]);

  // --- Route geometry ------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyRoute = () => {
      const source = map.getSource(ROUTE_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      if (!source) return;

      const coordinates = (routeCoordinates ?? []).map(toLngLat);
      source.setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } });

      if (coordinates.length > 1) {
        const bounds = coordinates.reduce(
          (acc, coord) => acc.extend(coord as [number, number]),
          new maplibregl.LngLatBounds(coordinates[0] as [number, number], coordinates[0] as [number, number]),
        );
        map.fitBounds(bounds, { padding: 64, animate: !reducedMotion, maxZoom: 12 });
      }
    };

    if (map.loaded()) applyRoute();
    else map.once("load", applyRoute);
  }, [routeCoordinates, reducedMotion]);

  // No custom ARIA role here — MapLibre manages accessibility on the
  // canvas it mounts inside this container itself (a focusable, keyboard-
  // pannable region), and overriding it risks contradicting that.
  return (
    <div
      ref={containerRef}
      className={`orca-map-dark-tiles ${className ?? ""}`}
      aria-label="Interactive map of the Mangaluru-Udupi coastal demo region"
    />
  );
}
