import { ChevronDown } from "lucide-react";
import { useState } from "react";

function Swatch({ color, shape = "square" }: { color: string; shape?: "square" | "circle" | "line" }) {
  if (shape === "line") {
    return <span className="inline-block h-0.5 w-4 rounded-full" style={{ backgroundColor: color }} />;
  }
  return (
    <span
      className={`inline-block h-3 w-3 border border-black/10 ${shape === "circle" ? "rounded-full" : "rounded-sm"}`}
      style={{ backgroundColor: color }}
    />
  );
}

function Row({ color, label, shape }: { color: string; label: string; shape?: "square" | "circle" | "line" }) {
  return (
    <div className="flex items-center gap-2 text-xs text-marine-ink">
      <Swatch color={color} shape={shape} />
      <span>{label}</span>
    </div>
  );
}

// Phase 8 (task §18) — every legend section is keyed so a caller can pass
// `only` to show just the sections relevant to whichever layer(s) are
// currently active (the Dashboard's compact map does this); omitting
// `only` (every pre-Phase-8 caller) keeps the full, unfiltered legend
// exactly as before — zero behavior change for MarineMapPage/SafetyPage.
export type MapLegendSectionKey = "risk" | "fishing" | "safety" | "hazards" | "marine" | "reference" | "route";

/**
 * A single collapsible legend distinguishing authoritative (deterministic
 * ORCA output), reference (official-but-unavailable INCOIS PFZ), and
 * illustrative (demo-only geofence) layers — never presenting one as the
 * other.
 */
export function MapLegend({ only }: { only?: MapLegendSectionKey[] } = {}) {
  const [collapsed, setCollapsed] = useState(true);
  const show = (key: MapLegendSectionKey) => !only || only.includes(key);

  return (
    <div className="pointer-events-auto w-64 rounded-xl border border-marine-border bg-marine-surface text-marine-ink shadow-lg">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-3.5 py-3 text-sm font-semibold uppercase tracking-wide text-marine-blue"
      >
        Legend
        <ChevronDown size={16} className={`transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>

      {!collapsed && (
        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-3 pb-3 text-xs">
          {show("risk") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Risk (deterministic ORCA Risk Engine)</p>
              <Row color="#10B981" label="Low" />
              <Row color="#F59E0B" label="Moderate" />
              <Row color="#EF4444" label="High" />
              <Row color="#475569" label="Blocked (see geofences)" />
            </section>
          )}

          {show("fishing") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Fishing</p>
              <Row color="#10B981" label="ORCA High Suitability" shape="circle" />
              <Row color="#7DD3FC" label="ORCA Moderate Suitability" shape="circle" />
              <Row color="#F59E0B" label="ORCA Low Suitability" shape="circle" />
              <Row color="#64748B" label="Not Recommended" shape="circle" />
              <p className="pt-1 text-[10px] italic text-marine-ink-muted/70">
                INCOIS PFZ Reference — not available in this deployment (never fabricated).
              </p>
            </section>
          )}

          {show("safety") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Safety</p>
              <Row color="#EF4444" label="Restricted / Geofenced Zone (illustrative demo fixture)" />
            </section>
          )}

          {show("hazards") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Marine Hazards (Phase 4 — real detected hazards)</p>
              <Row color="#FACC15" label="Advisory (cyclone: GDACS Green; wave/wind approaching threshold)" shape="circle" />
              <Row color="#F59E0B" label="Warning (thunderstorm proxy; elevated wave/wind)" shape="circle" />
              <Row color="#EF4444" label="Danger (wave/wind at Risk Engine threshold)" shape="circle" />
              <Row color="#BE185D" label="Critical (active cyclone — GDACS Red)" shape="circle" />
              <p className="pt-1 text-[10px] italic text-marine-ink-muted/70">
                Lightning/thunderstorm detection is UNAVAILABLE (no public real-time API) — shown as a coarse weather-code proxy only, never claimed as real detection.
              </p>
            </section>
          )}

          {show("marine") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Marine (real Open-Meteo samples)</p>
              <Row color="#38BDF8" label="SST — cool" shape="circle" />
              <Row color="#F59E0B" label="SST — warm" shape="circle" />
              <Row color="#1E6FA8" label="Wave height (radius ∝ height)" shape="circle" />
              <Row color="#7DD3FC" label="Current direction (schematic, length ∝ speed)" shape="line" />
            </section>
          )}

          {show("reference") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Reference (GEBCO / INCOIS)</p>
              <Row color="#7DD3FC" label="Bathymetry — shallow" shape="circle" />
              <Row color="#0F3A5F" label="Bathymetry — deep" shape="circle" />
              <Row color="#F0F0C8" label="Chlorophyll — low" shape="circle" />
              <Row color="#1E5A10" label="Chlorophyll — high" shape="circle" />
              <p className="pt-1 text-[10px] italic text-marine-ink-muted/70">GEBCO bathymetry is reference/supporting data, not a navigation safety guarantee.</p>
            </section>
          )}

          {show("route") && (
            <section className="space-y-1">
              <p className="font-semibold text-marine-ink-muted">Route</p>
              <Row color="#38BDF8" label="Selected route" shape="line" />
              <Row color="#EF4444" label="Higher-risk route segment" shape="line" />
              <Row color="#94A3B8" label="Alternative route (not selected)" shape="line" />
              <Row color="#EF4444" label="Blocked route option (unsafe)" shape="line" />
              <Row color="#38BDF8" label="Origin" shape="circle" />
              <Row color="#D4A574" label="Destination" shape="circle" />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
