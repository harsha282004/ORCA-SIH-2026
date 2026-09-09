import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

import { RevealOnScroll } from "../common/RevealOnScroll";

// The actual tools now live on their own dedicated pages (real routes, not
// in-page anchors) — this section is the landing page's entry point into
// them, not a duplicate of the tools themselves.
const ENTRY_POINTS = [
  {
    title: "Ask ORCA",
    description: "Ask a natural-language question about fishing safety or conditions in the Mangaluru–Udupi coastal region.",
    href: "/ask-orca",
  },
  {
    title: "Plan a Route",
    description: "Get a deterministic, risk-aware route between two points that avoids hazards and restricted zones, on a real coastal map.",
    href: "/route-planner",
  },
  {
    title: "System Status",
    description: "See live backend, database, and cache health — the same readiness check ORCA itself depends on.",
    href: "/status",
  },
];

// Theme correction: converted to LIGHT so the page alternates after the
// dark AIIntelligenceSection right above it — white product-entry cards on
// an off-white section, matching task §16's light-card spec.
export function ProductExperienceSection() {
  return (
    <section className="bg-marine-surface-alt px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-6xl">
        <RevealOnScroll className="max-w-2xl">
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">The Product Experience</p>
          <h2 className="mt-4 text-3xl font-semibold tracking-tight text-marine-ink sm:text-5xl">
            Everything above is the real ORCA.
          </h2>
          <p className="mt-5 text-sm leading-relaxed text-marine-ink-muted sm:text-base">
            No mockups, no fabricated data — Ask ORCA and Route Planner call ORCA's live backend directly. Open
            either below, or check the system's own health.
          </p>
        </RevealOnScroll>

        <div className="mt-16 grid gap-5 sm:grid-cols-3">
          {ENTRY_POINTS.map((entry, index) => (
            <RevealOnScroll key={entry.title} delayMs={index * 80}>
              <Link
                to={entry.href}
                className="group block h-full rounded-2xl border border-marine-border bg-marine-surface p-6 shadow-sm transition-colors hover:border-marine-blue/40 hover:shadow-md"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-xl font-semibold text-marine-ink">{entry.title}</h3>
                  <ArrowUpRight className="h-5 w-5 text-marine-blue/70 transition-colors group-hover:text-marine-blue" strokeWidth={1.75} />
                </div>
                <p className="mt-3 text-sm leading-relaxed text-marine-ink-muted">{entry.description}</p>
              </Link>
            </RevealOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
