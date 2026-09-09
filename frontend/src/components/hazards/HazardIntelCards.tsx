import { CloudLightning, Wind } from "lucide-react";

import type { Hazard } from "../../lib/api";

/**
 * Phase 4/6 — the ONE shared cyclone/thunderstorm presentation used by
 * Dashboard, Marine Safety, and (where relevant) Ask ORCA's evidence
 * rendering. All three read the SAME `hazards[]` array the backend's
 * `app.hazard.engine.detect_all_hazards` already produces
 * (`GET /api/v1/safety/status` / `/hazards`) — this component classifies
 * nothing itself, it only renders fields that already exist on each
 * `Hazard` object. A cyclone is never invented; a thunderstorm status is
 * never claimed as real-time lightning detection (see `ThunderstormCard`'s
 * own permanent disclaimer).
 */

function fmt(dt?: string | null): string | null {
  if (!dt) return null;
  try {
    return new Date(dt).toLocaleString();
  } catch {
    return dt;
  }
}

// Theme correction: yellow-400/pink-400 read fine on dark navy but wash
// out to near-illegible on white — darkened to AA-readable equivalents,
// same semantic hue family.
const SEVERITY_TEXT: Record<string, string> = {
  INFO: "text-marine-ink-muted",
  ADVISORY: "text-[#92600A]",
  WARNING: "text-marine-warning",
  DANGER: "text-marine-danger",
  CRITICAL: "text-[#9D174D]",
};

export function CycloneCard({ hazards }: { hazards: Hazard[] }) {
  const cyclones = hazards.filter((h) => h.hazard_type === "CYCLONE");

  return (
    <div className="rounded-2xl border border-marine-border bg-marine-surface p-5 shadow-sm">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Cyclone</h3>
      {cyclones.length === 0 ? (
        <p className="mt-3 text-base font-medium text-marine-success">NO ACTIVE CYCLONE DETECTED</p>
      ) : (
        <div className="mt-3 space-y-4">
          {cyclones.map((c, i) => (
            <div key={i} className="space-y-1.5 text-sm text-marine-ink-muted">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-lg font-semibold text-marine-ink">{c.title}</span>
                <span className={`text-sm font-semibold ${SEVERITY_TEXT[c.severity] ?? "text-marine-ink-muted"}`}>{c.severity}</span>
              </div>
              <p>Status: ACTIVE (currently reported by the issuing authority)</p>
              {(c.valid_from || c.valid_until) && (
                <p>
                  Expected period: {fmt(c.valid_from) ?? "unknown start"} – {fmt(c.valid_until) ?? "ongoing"}
                </p>
              )}
              {c.distance_km != null && <p>Distance from selected location: {c.distance_km.toFixed(0)} km</p>}
              <p>Source: {c.source}</p>
              {c.observed_at && <p className="text-xs text-marine-ink-muted/80">Updated: {fmt(c.observed_at)}</p>}
              {c.description && <p className="text-xs italic leading-relaxed text-marine-ink-muted/80">{c.description}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ThunderstormCard({ hazards }: { hazards: Hazard[] }) {
  const proxy = hazards.find((h) => h.hazard_type === "THUNDERSTORM_PROXY");

  return (
    <div className="rounded-2xl border border-marine-border bg-marine-surface p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <CloudLightning size={16} className="text-marine-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-marine-blue">Thunderstorm Proxy</h3>
      </div>
      {!proxy ? (
        <p className="mt-3 text-base font-medium text-marine-success">NO SIGNIFICANT THUNDERSTORM ACTIVITY FORECAST</p>
      ) : (
        <div className="mt-3 space-y-1.5 text-sm text-marine-ink-muted">
          <p className="text-lg font-semibold text-marine-warning">Status: ELEVATED</p>
          {proxy.observed_at && <p>Forecast hour: {fmt(proxy.observed_at)}</p>}
          <p>Risk: {proxy.severity}</p>
          <p>Source: {proxy.source}</p>
        </div>
      )}
      <p className="mt-3 flex items-start gap-1.5 text-xs italic leading-relaxed text-marine-ink-muted/70">
        <Wind size={12} className="mt-0.5 shrink-0" />
        No public real-time lightning-detection API exists for this region (DAMINI/IMD is the authoritative source and is not
        integrated). This is a WMO weather-code forecast proxy, never real-time lightning detection.
      </p>
    </div>
  );
}
