/**
 * Phase 8 — the second reusable chart primitive: a categorical comparison
 * (baseline vs scenario, Route A vs B vs C). Same zero-dependency SVG
 * approach as LineSeriesChart, deliberately reused rather than a second
 * charting library.
 */
export interface BarGroup {
  key: string;
  label: string;
  value: number;
  unit?: string;
  color?: string;
  sublabel?: string;
}

interface ComparisonBarChartProps {
  groups: BarGroup[];
  height?: number;
  emptyLabel?: string;
}

const DEFAULT_COLORS = ["#38BDF8", "#F59E0B", "#7DD3FC", "#10B981"];

export function ComparisonBarChart({ groups, height = 160, emptyLabel = "DATA UNAVAILABLE" }: ComparisonBarChartProps) {
  if (groups.length === 0) {
    return (
      <div style={{ height }} className="flex items-center justify-center rounded-lg border border-dashed border-marine-border text-xs font-semibold uppercase tracking-wide text-marine-ink-muted">
        {emptyLabel}
      </div>
    );
  }

  const max = Math.max(...groups.map((g) => Math.abs(g.value)), 0.001);
  const width = 640;
  const barAreaHeight = height - 48;
  const barWidth = Math.min(80, (width / groups.length) * 0.5);

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Comparison chart">
        {groups.map((g, i) => {
          const slot = width / groups.length;
          const cx = slot * i + slot / 2;
          const barHeight = (Math.abs(g.value) / max) * (barAreaHeight - 20);
          const barY = 8 + (barAreaHeight - 20) - barHeight;
          const color = g.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length];
          return (
            <g key={g.key}>
              <rect x={cx - barWidth / 2} y={barY} width={barWidth} height={Math.max(barHeight, 1)} rx={3} fill={color} fillOpacity={0.9} />
              <text x={cx} y={barY - 6} textAnchor="middle" fontSize={11} fontWeight={600} fill="#0B2B45">
                {g.value.toFixed(2)}
                {g.unit ? ` ${g.unit}` : ""}
              </text>
              <text x={cx} y={height - 24} textAnchor="middle" fontSize={10} fill="#4B6478">
                {g.label}
              </text>
              {g.sublabel && (
                <text x={cx} y={height - 10} textAnchor="middle" fontSize={9} fill="#4B6478" fillOpacity={0.8}>
                  {g.sublabel}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      <table className="sr-only">
        <caption>Comparison chart — real values</caption>
        <tbody>
          {groups.map((g) => (
            <tr key={g.key}>
              <td>{g.label}</td>
              <td>
                {g.value}
                {g.unit ?? ""}
              </td>
              <td>{g.sublabel ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
