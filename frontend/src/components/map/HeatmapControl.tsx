import { ChevronDown } from "lucide-react";
import { useState } from "react";

import type { HeatmapVariable } from "./mapLayers";

export interface HeatmapOption {
  value: HeatmapVariable;
  label: string;
  unit: string;
  available: boolean;
  unavailableReason?: string;
}

interface HeatmapControlProps {
  options: HeatmapOption[];
  value: HeatmapVariable | null;
  onChange: (value: HeatmapVariable | null) => void;
  /** Real-data status for whichever variable is currently selected — never
   * a generic spinner once loaded, always what actually happened. */
  status: "idle" | "loading" | "ready" | "unavailable" | "error";
  statusMessage?: string;
  extent?: { min: number; max: number } | null;
}

/**
 * Phase 12 — the Marine Map's heatmap layer selector. Every option here
 * corresponds to a real, already-fetched multi-point data source
 * (mapLayers.ts's own HEATMAP_VALUE_FIELD/buildHeatmapLayer) — an option
 * with `available: false` is rendered disabled with its reason, never
 * silently hidden or silently enabled without real backing data.
 */
export function HeatmapControl({ options, value, onChange, status, statusMessage, extent }: HeatmapControlProps) {
  const [collapsed, setCollapsed] = useState(true);
  const selected = options.find((o) => o.value === value);

  return (
    <div className="pointer-events-auto w-72 rounded-xl border border-marine-cyan/20 bg-marine-deep/95 text-marine-white shadow-lg backdrop-blur">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-3.5 py-3 text-sm font-semibold uppercase tracking-wide text-marine-cyan-light"
      >
        <span>Heatmap{selected ? `: ${selected.label}` : ""}</span>
        <ChevronDown size={16} className={`transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>

      {!collapsed && (
        <div className="space-y-3 px-3.5 pb-3.5">
          <select
            value={value ?? "off"}
            onChange={(e) => onChange(e.target.value === "off" ? null : (e.target.value as HeatmapVariable))}
            className="w-full rounded-lg border border-marine-cyan/25 bg-marine-deep/60 px-3 py-2 text-sm text-marine-white focus:border-marine-cyan focus:outline-none"
          >
            <option value="off">Off</option>
            {options.map((o) => (
              <option key={o.value} value={o.value} disabled={!o.available}>
                {o.label}
                {!o.available ? " (unavailable)" : ""}
              </option>
            ))}
          </select>

          {selected && !selected.available && (
            <p className="text-xs italic text-marine-warning">{selected.unavailableReason}</p>
          )}

          {value && status === "loading" && <p className="text-xs text-marine-white/50">Loading real spatial data…</p>}
          {value && status === "error" && <p className="text-xs text-marine-danger">{statusMessage ?? "Could not load spatial data."}</p>}
          {value && status === "unavailable" && (
            <div className="rounded-lg border border-marine-warning/30 bg-marine-warning/5 p-2.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-marine-warning">Heatmap Unavailable</p>
              <p className="mt-1 text-xs text-marine-white/60">Insufficient spatial data is currently available for this layer.</p>
            </div>
          )}
          {value && status === "ready" && selected && extent && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-marine-white/40">{selected.label}</p>
              <div className="h-2 w-full rounded-full bg-gradient-to-r from-marine-blue via-marine-cyan to-marine-sand" />
              <div className="mt-1 flex justify-between text-xs text-marine-white/60">
                <span>
                  {extent.min.toFixed(2)} {selected.unit}
                </span>
                <span>
                  {extent.max.toFixed(2)} {selected.unit}
                </span>
              </div>
              <p className="mt-1 text-[10px] italic text-marine-white/30">Real range of the currently loaded sample points — never a fixed/invented scale.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
