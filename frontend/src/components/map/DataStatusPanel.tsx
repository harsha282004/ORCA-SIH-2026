import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { FreshnessBadge } from "./FreshnessBadge";
import type { MapLayerState } from "../../hooks/useMapLayer";

interface StatusRow {
  label: string;
  state: MapLayerState<unknown> | "not-enabled" | "static-unavailable";
  /** Phase 2 §19 — an honest coverage note ("225 samples", "51/64 samples"),
   * read from the layer's own real meta, never invented here. Shown only
   * when the layer is actually loaded. */
  sampleNote?: string;
}

function metaStatus(meta: unknown): string {
  if (meta && typeof meta === "object" && "status" in meta && typeof (meta as { status: unknown }).status === "string") {
    return (meta as { status: string }).status;
  }
  // Per-sample layers (oceanography, suitability) carry status on each
  // GeoJSON feature, not on the aggregate `meta` — a successful fetch of
  // one of these is reported as CURRENT/FORECAST at the individual feature
  // level (see EvidencePanel); the aggregate row simply confirms the fetch
  // itself succeeded.
  return "FORECAST";
}

function rowStatus(row: StatusRow): string {
  if (row.state === "not-enabled") return "OFF";
  if (row.state === "static-unavailable") return "UNAVAILABLE";
  switch (row.state.kind) {
    case "idle":
      return "OFF";
    case "loading":
      return "LOADING";
    case "error":
      return "UNAVAILABLE";
    case "unavailable":
      return "UNAVAILABLE";
    case "loaded":
      return metaStatus(row.state.meta);
    default:
      return "UNAVAILABLE";
  }
}

/**
 * A compact readout of every enabled layer's ACTUAL freshness status, as
 * returned by the backend — never a guess derived from "a response
 * arrived" (architecture.md §17's Temporal Validity Gate discipline:
 * "latest response received" is never treated as "live").
 *
 * Redesign note (map-overlap fix): this panel used to render fully
 * expanded at all times, anchored to a map corner independently of
 * LayerControlPanel — with several layers enabled, both panels grew tall
 * enough to visually collide (Route Planner/Fishing/Marine Map all showed
 * this). It now collapses to a one-line header by default, exactly like
 * MapLegend already did, so no floating map panel is ever taller than
 * necessary unless a person deliberately opens it.
 */
export function DataStatusPanel({ rows }: { rows: StatusRow[] }) {
  const [collapsed, setCollapsed] = useState(true);
  const liveCount = rows.filter((r) => rowStatus(r) !== "OFF").length;

  return (
    <div className="pointer-events-auto w-64 rounded-xl border border-marine-cyan/20 bg-marine-deep/90 text-marine-white shadow-lg backdrop-blur">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-sm font-semibold uppercase tracking-wide text-marine-cyan-light"
      >
        <span>
          Data Status
          {liveCount > 0 && <span className="ml-2 text-[11px] font-normal normal-case text-marine-white/40">{liveCount} active</span>}
        </span>
        <ChevronDown size={16} className={`transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>

      {!collapsed && (
        <div className="max-h-[50vh] space-y-2 overflow-y-auto px-3 pb-3">
          {rows.map((row) => {
            const status = rowStatus(row);
            const showNote = row.sampleNote && typeof row.state === "object" && row.state.kind === "loaded";
            return (
              <div key={row.label} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-marine-white/70">{row.label}</span>
                  {status === "LOADING" ? (
                    <span className="text-xs text-marine-white/40">loading…</span>
                  ) : status === "OFF" ? (
                    <span className="text-xs text-marine-white/30">off</span>
                  ) : (
                    <FreshnessBadge status={status} />
                  )}
                </div>
                {showNote && <span className="text-right text-xs text-marine-white/40">{row.sampleNote}</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export type { StatusRow };
