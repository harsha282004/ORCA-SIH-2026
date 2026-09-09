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
  /** Redesign note (map-overlap fix): this panel used to default to
   * expanded, which — combined with DataStatusPanel also being expanded by
   * default in the opposite corner — routinely grew tall enough to cover a
   * large fraction of the map and collide with the other panel (Dashboard/
   * Fishing/Marine Map/Route Planner all showed this). It now defaults to
   * collapsed everywhere unless a caller has a specific reason not to. */
  defaultCollapsed?: boolean;
}

/**
 * The map's layer control — organized by category, matching the SIH
 * demonstration's own grouping. A layer with no real backend data is
 * rendered disabled (never a silently-inert checkbox that looks the same
 * as a working one) with its unavailability reason as a tooltip.
 */
export function LayerControlPanel({ groups, enabled, onToggle, onRefresh, refreshing, defaultCollapsed = true }: LayerControlPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const activeCount = Object.values(enabled).filter(Boolean).length;

  return (
    <div className="pointer-events-auto w-72 rounded-xl border border-marine-cyan/20 bg-marine-deep/95 text-marine-white shadow-lg backdrop-blur">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-3.5 py-3 text-sm font-semibold uppercase tracking-wide text-marine-cyan-light"
      >
        <span>
          Map Layers
          {activeCount > 0 && <span className="ml-2 text-[11px] font-normal normal-case text-marine-white/40">{activeCount} on</span>}
        </span>
        <ChevronDown size={16} className={`transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>

      {!collapsed && (
        <div className="max-h-[55vh] space-y-4 overflow-y-auto px-3.5 pb-3.5">
          {groups.map((group) => (
            <div key={group.title}>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-marine-white/40">{group.title}</p>
              <div className="space-y-1">
                {group.layers.map((layer) => (
                  <label
                    key={layer.key}
                    title={layer.available ? undefined : layer.unavailableReason ?? "Not available in this deployment"}
                    className={`flex items-center gap-2.5 rounded px-1.5 py-1.5 text-sm ${
                      layer.available ? "cursor-pointer hover:bg-marine-cyan/10" : "cursor-not-allowed opacity-40"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={!!enabled[layer.key]}
                      disabled={!layer.available}
                      onChange={() => layer.available && onToggle(layer.key)}
                      className="h-4 w-4 accent-marine-cyan"
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
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-marine-cyan/25 bg-marine-cyan/10 px-3 py-2.5 text-sm font-medium text-marine-cyan-light transition-colors hover:bg-marine-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Refreshing…" : "Refresh Data"}
          </button>
        </div>
      )}
    </div>
  );
}
