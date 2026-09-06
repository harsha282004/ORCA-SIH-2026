// The original Phase 0 system-status dashboard — preserved functionality,
// restyled to the deep-marine theme. Logic is unchanged: it still reuses
// the shared API client (lib/api.ts) and the real GET /api/v1/health/ready
// check, polled every 10 seconds. Never fabricates a dependency's status.
import { useEffect, useState } from "react";

import { getReadiness, type DependencyStatus, type ReadinessResponse } from "../lib/api";

type ReadinessState =
  | { kind: "loading" }
  | { kind: "unreachable"; message: string }
  | { kind: "loaded"; data: ReadinessResponse };

function badgeClasses(healthy: boolean | null): string {
  if (healthy === null) return "bg-marine-white/10 text-marine-white/60";
  return healthy ? "bg-marine-success/20 text-marine-success" : "bg-marine-danger/20 text-marine-danger";
}

function StatusRow({ label, status }: { label: string; status: DependencyStatus | null }) {
  const healthy = status === null ? null : status === "healthy";
  const text = status === null ? "unknown" : status;
  return (
    <div className="flex items-center justify-between border-b border-marine-cyan/10 py-3 last:border-b-0">
      <span className="text-marine-white">{label}</span>
      <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${badgeClasses(healthy)}`}>
        {text}
      </span>
    </div>
  );
}

export function StatusPage() {
  const [state, setState] = useState<ReadinessState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function fetchReadiness() {
      try {
        const data = await getReadiness();
        if (!cancelled) setState({ kind: "loaded", data });
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "unreachable",
            message: err instanceof Error ? err.message : "Unknown error",
          });
        }
      }
    }

    fetchReadiness();
    const interval = window.setInterval(fetchReadiness, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const backendReachable = state.kind === "loaded" ? true : state.kind === "unreachable" ? false : null;
  const dependencies = state.kind === "loaded" ? state.data.dependencies : null;

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-marine-deep px-4 pt-24 text-marine-white">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(56,189,248,0.08),_transparent_65%)]"
        aria-hidden="true"
      />
      <div className="relative w-full max-w-md">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">ORCA System Status</p>
        <h1 className="mt-3 text-4xl font-bold tracking-tight text-marine-white">ORCA</h1>
        <p className="mt-1 text-marine-white/60">Marine EcOsystem Reasoning with Collaborative Agents</p>

        <div className="mt-8 rounded-2xl border border-marine-cyan/15 bg-marine-ocean/40 p-5 shadow-sm backdrop-blur-sm">
          <h2 className="mb-2 text-lg font-semibold text-marine-white">System Status</h2>

          <StatusRow label="Backend" status={backendReachable ? "healthy" : backendReachable === false ? "unhealthy" : null} />
          <StatusRow label="PostgreSQL" status={dependencies?.database ?? null} />
          <StatusRow label="PostGIS" status={dependencies?.postgis ?? null} />
          <StatusRow label="Redis" status={dependencies?.redis ?? null} />

          {state.kind === "loading" && <p className="pt-3 text-sm text-marine-white/60">Checking backend status...</p>}
          {state.kind === "unreachable" && (
            <p className="pt-3 text-sm text-marine-danger">Backend unavailable: {state.message}</p>
          )}
        </div>

        <p className="mt-6 text-xs text-marine-white/50">
          Live readiness check against PostgreSQL, PostGIS, and Redis — refreshed every 10 seconds.
        </p>
      </div>
    </main>
  );
}
