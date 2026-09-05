import { useEffect, useState } from "react";

import { API_BASE_URL } from "./config";

type DependencyStatus = "healthy" | "unhealthy";

interface ReadinessResponse {
  status: "ready" | "not_ready";
  dependencies: {
    database: DependencyStatus;
    postgis: DependencyStatus;
    redis: DependencyStatus;
  };
}

type ReadinessState =
  | { kind: "loading" }
  | { kind: "unreachable"; message: string }
  | { kind: "loaded"; data: ReadinessResponse };

function badgeClasses(healthy: boolean | null): string {
  if (healthy === null) return "bg-slate-500";
  return healthy ? "bg-emerald-600" : "bg-red-600";
}

function StatusRow({ label, status }: { label: string; status: DependencyStatus | null }) {
  const healthy = status === null ? null : status === "healthy";
  const text = status === null ? "unknown" : status;
  return (
    <div className="flex items-center justify-between border-b border-slate-700 py-2 last:border-b-0">
      <span className="text-slate-200">{label}</span>
      <span className={`rounded px-2 py-0.5 text-sm font-medium text-white ${badgeClasses(healthy)}`}>
        {text}
      </span>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<ReadinessState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function fetchReadiness() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/health/ready`);
        const data = (await response.json()) as ReadinessResponse;
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
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4 text-slate-100">
      <div className="w-full max-w-md">
        <h1 className="text-4xl font-bold tracking-tight">ORCA</h1>
        <p className="mt-1 text-slate-400">Marine EcOsystem Reasoning with Collaborative Agents</p>

        <div className="mt-8 rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="mb-2 text-lg font-semibold">System Status</h2>

          <StatusRow label="Backend" status={backendReachable ? "healthy" : backendReachable === false ? "unhealthy" : null} />
          <StatusRow label="PostgreSQL" status={dependencies?.database ?? null} />
          <StatusRow label="PostGIS" status={dependencies?.postgis ?? null} />
          <StatusRow label="Redis" status={dependencies?.redis ?? null} />

          {state.kind === "loading" && (
            <p className="pt-3 text-sm text-slate-400">Checking backend status...</p>
          )}
          {state.kind === "unreachable" && (
            <p className="pt-3 text-sm text-red-400">Backend unavailable: {state.message}</p>
          )}
        </div>

        <p className="mt-6 text-xs text-slate-500">
          Phase 0 — Infrastructure only. No marine-intelligence functionality is implemented yet.
        </p>
      </div>
    </div>
  );
}
