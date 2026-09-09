const STYLES: Record<string, string> = {
  CURRENT: "border-marine-success/40 bg-marine-success/15 text-marine-success",
  FORECAST: "border-marine-cyan/40 bg-marine-cyan/15 text-marine-cyan-light",
  CACHED: "border-marine-sand/40 bg-marine-sand/15 text-marine-sand",
  STALE: "border-marine-warning/40 bg-marine-warning/15 text-marine-warning",
  STATIC: "border-marine-white/25 bg-marine-white/10 text-marine-white/70",
  UNAVAILABLE: "border-marine-danger/40 bg-marine-danger/15 text-marine-danger",
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
