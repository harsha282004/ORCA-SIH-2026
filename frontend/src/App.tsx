import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { Footer } from "./components/layout/Footer";
import { Navbar } from "./components/layout/Navbar";
import { AskOrcaPage } from "./routes/AskOrcaPage";
import { HomePage } from "./routes/HomePage";
import { StatusPage } from "./routes/StatusPage";

// Code-split: RoutePlannerPage pulls in maplibre-gl (a real WebGL map
// engine, ~800kB) — lazy-loading it means that weight is only ever
// downloaded by a visitor who actually opens the Route Planner, never by
// the landing page (which is already the most performance-sensitive page,
// carrying the 1,200-frame cinematic sequence).
const RoutePlannerPage = lazy(() => import("./routes/RoutePlannerPage").then((m) => ({ default: m.RoutePlannerPage })));
// Same reasoning — the Marine Intelligence Map also mounts MapLibre/deck.gl.
const MarineMapPage = lazy(() => import("./routes/MarineMapPage").then((m) => ({ default: m.MarineMapPage })));
// Same reasoning — the Fishing Intelligence page also mounts MapLibre/deck.gl.
const FishingPage = lazy(() => import("./routes/FishingPage").then((m) => ({ default: m.FishingPage })));
// Same reasoning — the Marine Safety page (Phase 4) also mounts MapLibre/deck.gl.
const SafetyPage = lazy(() => import("./routes/SafetyPage").then((m) => ({ default: m.SafetyPage })));
// Same reasoning — the Dashboard (Phase 8) also mounts MapLibre/deck.gl.
const DashboardPage = lazy(() => import("./routes/DashboardPage").then((m) => ({ default: m.DashboardPage })));

function RouteLoadingFallback() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-marine-deep pt-20">
      <p className="text-sm font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Loading…</p>
    </main>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-marine-deep">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-marine-cyan focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-marine-deep"
      >
        Skip to content
      </a>
      <Navbar />
      <div id="main-content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/ask-orca" element={<AskOrcaPage />} />
          <Route
            path="/route-planner"
            element={
              <Suspense fallback={<RouteLoadingFallback />}>
                <RoutePlannerPage />
              </Suspense>
            }
          />
          <Route
            path="/marine-map"
            element={
              <Suspense fallback={<RouteLoadingFallback />}>
                <MarineMapPage />
              </Suspense>
            }
          />
          <Route
            path="/fishing"
            element={
              <Suspense fallback={<RouteLoadingFallback />}>
                <FishingPage />
              </Suspense>
            }
          />
          <Route
            path="/safety"
            element={
              <Suspense fallback={<RouteLoadingFallback />}>
                <SafetyPage />
              </Suspense>
            }
          />
          <Route
            path="/dashboard"
            element={
              <Suspense fallback={<RouteLoadingFallback />}>
                <DashboardPage />
              </Suspense>
            }
          />
          <Route path="/status" element={<StatusPage />} />
        </Routes>
      </div>
      <Footer />
    </div>
  );
}
