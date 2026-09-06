import { ChevronDown, Lock, RefreshCw } from "lucide-react";
import { useState } from "react";

export interface LayerToggle {
  key: string;
  label: string;
  available: boolean;
  unavailableReason?: string;
}

export interface LayerGroup {
  title: string;
  layers: LayerToggle[];
}

interface LayerControlPanelProps {
  groups: LayerGroup[];
  enabled: Record<string, boolean>;
  onToggle: (key: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}

/**
 * The map's layer control — organized by category, matching the SIH
 * demonstration's own grouping. A layer with no real backend data is
 * rendered disabled (never a silently-inert checkbox that looks the same
 * as a working one) with its unavailability reason as a tooltip.
 */
export function LayerControlPanel({ groups, enabled, onToggle, onRefresh, refreshing }: LayerControlPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="pointer-events-auto w-64 rounded-xl border border-marine-cyan/20 bg-marine-deep/90 text-marine-white shadow-lg backdrop-blur">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-marine-cyan-light"
      >
        Map Layers
        <ChevronDown size={14} className={`transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>

      {!collapsed && (
        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-3 pb-3">
          {groups.map((group) => (
            <div key={group.title}>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-marine-white/40">{group.title}</p>
              <div className="space-y-1">
                {group.layers.map((layer) => (
                  <label
                    key={layer.key}
                    title={layer.available ? undefined : layer.unavailableReason ?? "Not available in this deployment"}
                    className={`flex items-center gap-2 rounded px-1.5 py-1 text-sm ${
                      layer.available ? "cursor-pointer hover:bg-marine-cyan/10" : "cursor-not-allowed opacity-40"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={!!enabled[layer.key]}
                      disabled={!layer.available}
                      onChange={() => layer.available && onToggle(layer.key)}
                      className="h-3.5 w-3.5 accent-marine-cyan"
                    />
                    <span>{layer.label}</span>
                    {!layer.available && (
                      <span className="ml-auto flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-marine-warning/70">
                        <Lock size={10} /> Locked
                      </span>
                    )}
                  </label>
                ))}
              </div>
            </div>
          ))}

          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-marine-cyan/25 bg-marine-cyan/10 px-3 py-2 text-xs font-medium text-marine-cyan-light transition-colors hover:bg-marine-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Refreshing…" : "Refresh Data"}
          </button>
        </div>
      )}
    </div>
  );
}
