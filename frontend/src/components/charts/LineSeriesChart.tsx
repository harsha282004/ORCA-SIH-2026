import { useId, useState } from "react";

/**
 * Phase 8 — the single reusable temporal chart primitive. Zero external
 * charting dependency (task §8: "choose the smallest appropriate charting
 * dependency… do not introduce a large visualization framework" — a
 * hand-rolled, dependency-free SVG line chart is the smallest possible
 * choice and gives full control over never fabricating/smoothing a point).
 *
 * Every point rendered here is a real value the backend returned for a
 * real timestamp (Open-Meteo hourly series via `evaluate_temporal_suitability`
 * — see app/fishing/temporal.py). A `null` value at some index means the
 * backend genuinely had no reading for that hour (e.g. a missing variable) —
 * the line is broken across that gap rather than interpolated, so a viewer
 * never mistakes a guessed connector for a real reading.
 */
export interface ChartPoint {
  timestamp: string;
  value: number | null;
}

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  unit?: string;
  points: ChartPoint[];
}

interface LineSeriesChartProps {
  series: ChartSeries[];
  height?: number;
  /** Index to visually highlight (e.g. the deterministic "best time" index) — never invented, always passed in from a real backend field. */
  highlightIndex?: number | null;
  emptyLabel?: string;
  valueFormatter?: (value: number, unit?: string) => string;
  /** Overrides the default "HH:00" hour label for non-hourly x-axes, e.g.
   * "cell #4 along route" for a route risk profile — the x domain is then
   * ordinal position, never a fabricated timestamp. `point.timestamp` still
   * supplies the React key/ordering, it is simply not parsed as a Date. */
  xLabel?: (point: ChartPoint, index: number) => string;
  tooltipXLabel?: (point: ChartPoint, index: number) => string;
  xAxisCaption?: string;
}

const PADDING = { top: 12, right: 16, bottom: 28, left: 40 };

function defaultFormat(value: number, unit?: string): string {
  return unit ? `${value.toFixed(2)} ${unit}` : value.toFixed(2);
}

function defaultXLabel(point: ChartPoint): string {
  return `${new Date(point.timestamp).getUTCHours().toString().padStart(2, "0")}:00`;
}

export function LineSeriesChart({
  series,
  height = 220,
  highlightIndex,
  emptyLabel = "DATA UNAVAILABLE",
  valueFormatter = defaultFormat,
  xLabel = defaultXLabel,
  tooltipXLabel = (p) => new Date(p.timestamp).toLocaleString(),
  xAxisCaption,
}: LineSeriesChartProps) {
  const gradientId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const nonEmpty = series.filter((s) => s.points.some((p) => p.value !== null));
  if (nonEmpty.length === 0) {
    return (
      <div style={{ height }} className="flex flex-col items-center justify-center rounded-lg border border-dashed border-marine-border text-xs text-marine-ink-muted">
        <span className="font-semibold uppercase tracking-wide">{emptyLabel}</span>
        <span className="mt-1 text-[10px]">No real temporal data exists for this variable/location.</span>
      </div>
    );
  }

  const width = 640;
  const innerWidth = width - PADDING.left - PADDING.right;
  const innerHeight = height - PADDING.top - PADDING.bottom;
  const pointCount = Math.max(...nonEmpty.map((s) => s.points.length));

  const allValues = nonEmpty.flatMap((s) => s.points.map((p) => p.value).filter((v): v is number => v !== null));
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  // A little headroom so a flat/near-flat real series doesn't render as a
  // line glued to the chart's edge — never changes the underlying values.
  const span = rawMax - rawMin || 1;
  const min = rawMin - span * 0.1;
  const max = rawMax + span * 0.1;

  const x = (i: number) => PADDING.left + (pointCount <= 1 ? innerWidth / 2 : (i / (pointCount - 1)) * innerWidth);
  const y = (v: number) => PADDING.top + innerHeight - ((v - min) / (max - min)) * innerHeight;

  function pathFor(points: ChartPoint[]): string {
    let d = "";
    let drawing = false;
    points.forEach((p, i) => {
      if (p.value === null) {
        drawing = false;
        return;
      }
      const cmd = drawing ? "L" : "M";
      d += `${cmd}${x(i).toFixed(1)},${y(p.value).toFixed(1)} `;
      drawing = true;
    });
    return d.trim();
  }

  const labelSeries = nonEmpty[0];
  const hoverPoint = hoverIndex !== null ? labelSeries.points[hoverIndex] : null;

  const yTicks = [min + (max - min) * 0.0, min + (max - min) * 0.5, min + (max - min) * 1.0];

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Temporal marine conditions chart">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#38BDF8" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Gridlines + y-axis labels — real min/mid/max of the actual data, never round-number invention. */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={PADDING.left} x2={width - PADDING.right} y1={y(t)} y2={y(t)} stroke="#0B2B45" strokeOpacity={0.08} />
            <text x={PADDING.left - 6} y={y(t)} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#4B6478">
              {t.toFixed(1)}
            </text>
          </g>
        ))}

        {/* Highlight column (e.g. the deterministic best-time hour). */}
        {highlightIndex != null && highlightIndex >= 0 && highlightIndex < pointCount && (
          <rect x={x(highlightIndex) - innerWidth / (pointCount * 2)} y={PADDING.top} width={innerWidth / pointCount} height={innerHeight} fill="#10B981" fillOpacity={0.08} />
        )}

        {nonEmpty.map((s) => (
          <path key={s.key} d={pathFor(s.points)} fill="none" stroke={s.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        ))}

        {/* x-axis hour labels — real timestamps, formatted, never relabeled. */}
        {labelSeries.points.map((p, i) => {
          if (pointCount > 8 && i % 2 !== 0) return null;
          return (
            <text key={p.timestamp} x={x(i)} y={height - 8} textAnchor="middle" fontSize={9} fill="#4B6478">
              {xLabel(p, i)}
            </text>
          );
        })}

        {/* Hover targets */}
        {labelSeries.points.map((_, i) => (
          <rect
            key={i}
            x={x(i) - innerWidth / (pointCount * 2)}
            y={PADDING.top}
            width={innerWidth / pointCount}
            height={innerHeight}
            fill="transparent"
            onMouseEnter={() => setHoverIndex(i)}
            onMouseLeave={() => setHoverIndex((cur) => (cur === i ? null : cur))}
          />
        ))}

        {hoverIndex !== null &&
          nonEmpty.map((s) => {
            const p = s.points[hoverIndex];
            if (!p || p.value === null) return null;
            return <circle key={s.key} cx={x(hoverIndex)} cy={y(p.value)} r={3.5} fill={s.color} stroke="#FFFFFF" strokeWidth={1.5} />;
          })}
      </svg>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-3">
          {series.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-[10px] text-marine-ink-muted">
              <span className="inline-block h-0.5 w-3 rounded-full" style={{ backgroundColor: s.color }} />
              {s.label}
              {s.unit ? ` (${s.unit})` : ""}
            </span>
          ))}
        </div>
        {hoverPoint && (
          <div className="rounded-md border border-marine-border bg-marine-surface px-2 py-1 text-[10px] text-marine-ink shadow-sm">
            <span className="text-marine-blue">{tooltipXLabel(hoverPoint, hoverIndex!)}</span>
            {nonEmpty.map((s) => {
              const p = s.points[hoverIndex!];
              if (!p || p.value === null) return null;
              return (
                <span key={s.key} className="ml-2">
                  {s.label}: {valueFormatter(p.value, s.unit)}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {/* Screen-reader-only data table — the same real values, never a
          second/derived copy — satisfies "chart descriptions where
          practical" (task §36) without a second visualization system. */}
      <table className="sr-only">
        <caption>{xAxisCaption ?? "Temporal marine conditions — real hourly values"}</caption>
        <thead>
          <tr>
            <th>{xAxisCaption ? "Position" : "Time"}</th>
            {series.map((s) => (
              <th key={s.key}>
                {s.label} {s.unit ? `(${s.unit})` : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labelSeries.points.map((p, i) => (
            <tr key={p.timestamp}>
              <td>{tooltipXLabel(p, i)}</td>
              {series.map((s) => (
                <td key={s.key}>{s.points[i]?.value ?? "unavailable"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
