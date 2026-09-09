/**
 * Phase 8 — the ONE reusable, non-map Evidence Panel (task §6: "Do not
 * build separate evidence components for each page"). The map's own
 * click-to-inspect panel (components/map/EvidencePanel.tsx) already
 * satisfies the same visual language for a clicked map feature and is left
 * untouched; this component is for every OTHER surface that needs to show
 * "where did this number come from" — Dashboard, Ask ORCA, Fishing,
 * Safety, Route Planner, Scenarios — all built from the SAME `EvidenceRow`
 * shape, populated only from real fields already present on the backend
 * response being rendered. Nothing here invents a source, a timestamp, or
 * a coverage note.
 */
import { FreshnessBadge } from "../map/FreshnessBadge";

export type DataState = "LIVE" | "CACHED" | "STALE" | "STATIC" | "PARTIAL" | "UNAVAILABLE" | "NON-AUTHORITATIVE";

export interface EvidenceRow {
  source: string;
  variable: string;
  value: string;
  timestamp?: string | null;
  /** The backend's own freshness vocabulary when known verbatim (CURRENT/FORECAST/CACHED/STALE/STATIC/UNAVAILABLE — see FreshnessBadge). */
  freshness?: string | null;
  coverage?: string | null;
  confidence?: number | null;
  isAuthoritative?: boolean | null;
  details?: string | null;
}

/**
 * Derives the task's requested display vocabulary (LIVE/CACHED/STALE/
 * STATIC/PARTIAL/UNAVAILABLE/NON-AUTHORITATIVE, task §7) from fields the
 * backend ALREADY computed — never a client-side guess. `freshness` is the
 * backend's own `classify_freshness_status`/hazard-freshness value;
 * `isAuthoritative === false` (e.g. an illustrative CRZ buffer, a
 * model-derived hazard proxy) always renders NON-AUTHORITATIVE regardless
 * of freshness, since "how new" and "how official" are different axes and
 * neither should hide the other. `confidence` below a low threshold is
 * surfaced as PARTIAL when freshness itself doesn't already say STALE/
 * UNAVAILABLE — this mirrors the Risk Engine's own confidence formula
 * (architecture.md §22: freshness + completeness + agreement), it does not
 * invent a new one.
 */
export function deriveDataState(row: Pick<EvidenceRow, "freshness" | "confidence" | "isAuthoritative">): DataState {
  if (row.isAuthoritative === false) return "NON-AUTHORITATIVE";
  const f = (row.freshness ?? "").toUpperCase();
  if (f === "UNAVAILABLE" || f === "UNKNOWN") return "UNAVAILABLE";
  if (f === "STALE") return "STALE";
  if (f === "STATIC") return "STATIC";
  if (f === "CACHED") return "CACHED";
  if (row.confidence != null && row.confidence < 0.5) return "PARTIAL";
  if (f === "CURRENT" || f === "FORECAST") return "LIVE";
  return "LIVE";
}

const STATE_STYLE: Record<DataState, string> = {
  LIVE: "border-marine-success/40 bg-marine-success/10 text-marine-success",
  CACHED: "border-marine-sand/50 bg-marine-sand/15 text-[#8A5A2B]",
  STALE: "border-marine-warning/50 bg-marine-warning/10 text-[#92600A]",
  STATIC: "border-marine-border bg-marine-surface-alt text-marine-ink-muted",
  PARTIAL: "border-marine-warning/50 bg-marine-warning/10 text-[#92600A]",
  UNAVAILABLE: "border-marine-danger/40 bg-marine-danger/10 text-marine-danger",
  "NON-AUTHORITATIVE": "border-marine-border bg-marine-surface-alt text-marine-ink-muted",
};

export function DataStateBadge({ state }: { state: DataState }) {
  return <span className={`inline-block rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${STATE_STYLE[state]}`}>{state}</span>;
}

// Theme correction: this card used to be a translucent dark-glass tile
// (bg-marine-deep/60, white text) — correct on the old all-dark app pages,
// unreadable on the white/off-white surfaces those pages now use. It is
// now a genuine white card, matching task §16's "LIGHT SECTION CARDS:
// background white, border subtle light blue/gray, heading dark navy,
// body muted blue-gray."
export function EvidenceCard({ row }: { row: EvidenceRow }) {
  const state = deriveDataState(row);
  return (
    <div className="flex min-h-[168px] flex-col rounded-2xl border border-marine-border bg-marine-surface p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-marine-blue">{row.source}</p>
          <p className="mt-0.5 text-sm text-marine-ink-muted">{row.variable}</p>
        </div>
        <DataStateBadge state={state} />
      </div>
      <p className="mt-3 text-2xl font-semibold leading-tight text-marine-ink">{row.value}</p>
      <dl className="mt-3 space-y-1.5 text-xs text-marine-ink-muted">
        {row.timestamp && (
          <div className="flex justify-between gap-2">
            <dt>Updated</dt>
            <dd className="text-right text-marine-ink-muted">{new Date(row.timestamp).toLocaleString()}</dd>
          </div>
        )}
        {row.freshness && (
          <div className="flex items-center justify-between gap-2">
            <dt>Freshness</dt>
            <dd>
              <FreshnessBadge status={row.freshness} />
            </dd>
          </div>
        )}
        {row.coverage && (
          <div className="flex justify-between gap-2">
            <dt>Coverage</dt>
            <dd className="text-right text-marine-ink-muted">{row.coverage}</dd>
          </div>
        )}
        {row.confidence != null && (
          <div className="flex justify-between gap-2">
            <dt>Confidence</dt>
            <dd className="text-right text-marine-ink-muted">{(row.confidence * 100).toFixed(0)}%</dd>
          </div>
        )}
      </dl>
      {row.details && <p className="mt-3 text-xs italic leading-relaxed text-marine-ink-muted/80">{row.details}</p>}
    </div>
  );
}

export function EvidenceList({ title, rows }: { title?: string; rows: EvidenceRow[] }) {
  return (
    <section className="rounded-2xl border border-marine-border bg-marine-surface-alt p-6">
      {title && <h2 className="mb-4 text-base font-semibold uppercase tracking-wide text-marine-ink">{title}</h2>}
      {rows.length === 0 ? (
        <p className="text-sm text-marine-ink-muted">No evidence is available for this result.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row, i) => (
            <EvidenceCard key={`${row.source}-${row.variable}-${i}`} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}
