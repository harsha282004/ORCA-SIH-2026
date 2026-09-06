import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError, type GeoJsonFeatureCollection, type LayerApiResponse } from "../lib/api";

export type MapLayerState<TMeta, TResponse = unknown> =
  | { kind: "idle" }
  | { kind: "loading"; isRefresh: boolean }
  | { kind: "loaded"; data: GeoJsonFeatureCollection; meta: TMeta; raw: TResponse }
  | { kind: "unavailable"; meta: TMeta | null; reason: string }
  | { kind: "error"; message: string };

/**
 * Fetches one `GET /api/v1/layers/*` endpoint on demand (never eagerly for
 * layers the user has not enabled — "no unnecessary API requests") and
 * exposes a real loading/error/unavailable/loaded lifecycle so the map
 * never silently shows a blank layer. `enabled` mirrors the layer-control
 * checkbox; toggling it off does not clear already-fetched data (flipping
 * it back on re-shows the last real fetch instead of re-fetching
 * immediately), toggling it on for the first time triggers the fetch.
 *
 * `raw` on the `loaded` state carries the FULL response object (not just
 * `data`/`meta`) — needed by endpoints like `/layers/oceanography` whose
 * response also carries a sibling top-level block (`incois_sst`) beyond
 * the base `{data, meta, errors}` shape.
 */
export function useMapLayer<TMeta, TResponse extends LayerApiResponse<TMeta> = LayerApiResponse<TMeta>>(
  enabled: boolean,
  fetcher: () => Promise<TResponse>,
): { state: MapLayerState<TMeta, TResponse>; refresh: () => void } {
  const [state, setState] = useState<MapLayerState<TMeta, TResponse>>({ kind: "idle" });
  const hasFetchedRef = useRef(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback((isRefresh: boolean) => {
    setState((prev) => ({ kind: "loading", isRefresh: isRefresh && prev.kind === "loaded" }));
    fetcherRef
      .current()
      .then((response) => {
        if (response.errors && response.errors.length > 0) {
          setState({ kind: "error", message: response.errors[0].message });
          return;
        }
        if (!response.data) {
          setState({ kind: "unavailable", meta: response.meta, reason: (response.meta as { reason?: string } | null)?.reason ?? "Data unavailable." });
          return;
        }
        setState({ kind: "loaded", data: response.data, meta: response.meta as TMeta, raw: response });
      })
      .catch((err) => {
        const message = err instanceof ApiRequestError ? err.message : "Something went wrong while contacting ORCA.";
        setState({ kind: "error", message });
      });
  }, []);

  useEffect(() => {
    if (enabled && !hasFetchedRef.current) {
      hasFetchedRef.current = true;
      load(false);
    }
  }, [enabled, load]);

  const refresh = useCallback(() => {
    hasFetchedRef.current = true;
    load(true);
  }, [load]);

  return { state, refresh };
}
