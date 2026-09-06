import { useEffect, useRef, useState } from "react";

import { ApiRequestError, getMarineTimeseries, type MarineTimeseriesPoint } from "../lib/api";

export type TimeseriesState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; series: MarineTimeseriesPoint[] }
  | { kind: "error"; message: string };

/**
 * The real time-slider data source — `GET /api/v1/layers/marine-timeseries`
 * (built in Phase 1, wired to the UI for the first time in Phase 2). Fetches
 * ONCE per (latitude, longitude) when enabled; every returned timestamp is
 * Open-Meteo's own genuine forecast value for that hour — the selected
 * index below always indexes into that real array, never a relabeled copy
 * of one value.
 */
export function useMarineTimeseries(enabled: boolean, latitude: number, longitude: number) {
  const [state, setState] = useState<TimeseriesState>({ kind: "idle" });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const fetchedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const key = `${latitude},${longitude}`;
    if (fetchedForRef.current === key) return;
    fetchedForRef.current = key;
    setState({ kind: "loading" });
    getMarineTimeseries(latitude, longitude)
      .then((response) => {
        if (response.errors && response.errors.length > 0) {
          setState({ kind: "error", message: response.errors[0].message });
          return;
        }
        if (!response.data) {
          setState({ kind: "error", message: "No time-series data returned." });
          return;
        }
        setState({ kind: "loaded", series: response.data.series });
        setSelectedIndex(0);
      })
      .catch((err) => {
        const message = err instanceof ApiRequestError ? err.message : "Something went wrong while contacting ORCA.";
        setState({ kind: "error", message });
      });
  }, [enabled, latitude, longitude]);

  const selectedPoint = state.kind === "loaded" ? state.series[selectedIndex] : null;

  return { state, selectedIndex, setSelectedIndex, selectedPoint };
}
