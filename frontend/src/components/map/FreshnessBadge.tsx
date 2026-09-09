// Theme correction: FORECAST/STATIC used light-cyan-on-translucent and
// near-white-on-translucent text, calibrated for a dark glass card — both
// were functionally invisible once every panel that renders this badge
// moved to a white/off-white surface. Every status here now uses a
// solid-enough foreground color to stay readable on marine-surface/
// marine-surface-alt while keeping each status's own semantic hue.
const STYLES: Record<string, string> = {
  CURRENT: "border-marine-success/40 bg-marine-success/10 text-marine-success",
  FORECAST: "border-marine-blue/40 bg-marine-mist text-marine-blue",
  CACHED: "border-marine-sand/60 bg-marine-sand/15 text-[#8A5A2B]",
  STALE: "border-marine-warning/50 bg-marine-warning/10 text-[#92600A]",
  STATIC: "border-marine-border bg-marine-surface-alt text-marine-ink-muted",
  UNAVAILABLE: "border-marine-danger/40 bg-marine-danger/10 text-marine-danger",
};

/**
 * Renders one of the canonical freshness statuses backend/app/api/v1/
 * layers.py's `classify_freshness_status` returns — never invented client-
 * side, always the value the backend attached to the feature/layer.
 */
export function FreshnessBadge({ status }: { status: string }) {
  const style = STYLES[status] ?? STYLES.UNAVAILABLE;
  return <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${style}`}>{status}</span>;
}
