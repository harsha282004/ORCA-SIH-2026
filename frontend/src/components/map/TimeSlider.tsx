import { Clock } from "lucide-react";

import type { MarineTimeseriesPoint } from "../../lib/api";
import type { TimeseriesState } from "../../hooks/useMarineTimeseries";

interface TimeSliderProps {
  state: TimeseriesState;
  selectedIndex: number;
  onChange: (index: number) => void;
  point: MarineTimeseriesPoint | null;
}

function formatHour(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }) + "z";
}

const HEADLINE_VARS = ["sea_surface_temperature", "wave_height", "wind_speed_10m"];
const VAR_LABELS: Record<string, string> = { sea_surface_temperature: "SST", wave_height: "Wave", wind_speed_10m: "Wind" };

/**
 * A genuine time slider over `GET /api/v1/layers/marine-timeseries`'s real
 * 24-hour Open-Meteo series (backend/app/api/v1/layers.py) — every position
 * on the track corresponds to a real fetched timestamp; moving it re-reads
 * `state.series[index]`, it never just relabels the same value.
 */
export function TimeSlider({ state, selectedIndex, onChange, point }: TimeSliderProps) {
  if (state.kind === "idle" || state.kind === "loading") {
    return (
      <div className="pointer-events-auto w-full max-w-xl rounded-xl border border-marine-border bg-marine-surface px-4 py-3 text-xs text-marine-ink-muted shadow-lg">
        {state.kind === "loading" ? "Loading real hourly forecast series…" : "Enable a time-varying layer to load the time slider."}
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="pointer-events-auto w-full max-w-xl rounded-xl border border-marine-danger/40 bg-marine-surface px-4 py-3 text-xs text-marine-danger shadow-lg">
        Time series unavailable: {state.message}
      </div>
    );
  }

  const { series } = state;

  return (
    <div className="pointer-events-auto w-full max-w-xl rounded-xl border border-marine-border bg-marine-surface px-4 py-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 font-semibold uppercase tracking-wide text-marine-blue">
          <Clock size={13} />
          Forecast timeline — region reference point
        </span>
        <span className="text-marine-ink-muted">{point ? formatHour(point.timestamp) : "—"}</span>
      </div>

      <input
        type="range"
        min={0}
        max={series.length - 1}
        step={1}
        value={selectedIndex}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-marine-cyan"
        aria-label="Select forecast hour"
      />

      <div className="mt-1 flex justify-between text-[10px] text-marine-ink-muted">
        <span>{series.length > 0 ? formatHour(series[0].timestamp) : ""}</span>
        <span>{series.length > 0 ? formatHour(series[series.length - 1].timestamp) : ""}</span>
      </div>

      {point && (
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-marine-ink-muted">
          {HEADLINE_VARS.map((v) =>
            typeof point.values[v] === "number" ? (
              <span key={v}>
                {VAR_LABELS[v]}: <span className="text-marine-ink">{point.values[v]!.toFixed(1)}</span> {point.units[v]}
              </span>
            ) : null,
          )}
          <span className="ml-auto rounded-full border border-marine-cyan/30 bg-marine-mist px-2 py-0.5 text-marine-blue">FORECAST</span>
        </div>
      )}
    </div>
  );
}
