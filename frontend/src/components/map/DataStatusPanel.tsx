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
 * A compact, always-visible readout of every enabled layer's ACTUAL
 * freshness status, as returned by the backend — never a guess derived
 * from "a response arrived" (architecture.md §17's Temporal Validity
 * Gate discipline: "latest response received" is never treated as "live").
 */
export function DataStatusPanel({ rows }: { rows: StatusRow[] }) {
  return (
    <div className="pointer-events-auto w-56 rounded-xl border border-marine-cyan/20 bg-marine-deep/90 p-3 text-marine-white shadow-lg backdrop-blur">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-marine-cyan-light">ORCA Data Status</p>
      <div className="space-y-1.5">
        {rows.map((row) => {
          const status = rowStatus(row);
          const showNote = row.sampleNote && typeof row.state === "object" && row.state.kind === "loaded";
          return (
            <div key={row.label} className="flex flex-col gap-0.5">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-marine-white/70">{row.label}</span>
                {status === "LOADING" ? (
                  <span className="text-[10px] text-marine-white/40">loading…</span>
                ) : status === "OFF" ? (
                  <span className="text-[10px] text-marine-white/30">off</span>
                ) : (
                  <FreshnessBadge status={status} />
                )}
              </div>
              {showNote && <span className="text-right text-[10px] text-marine-white/40">{row.sampleNote}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export type { StatusRow };
