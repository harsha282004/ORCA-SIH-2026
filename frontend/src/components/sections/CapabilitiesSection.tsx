import { RevealOnScroll } from "../common/RevealOnScroll";

// Every capability maps to a real, implemented backend module — see
// backend/app/{risk,suitability,gis,routing,policy,decision,agents,
// orchestration}. Nothing here is aspirational.
const CAPABILITIES = [
  {
    title: "Conversational Intelligence",
    description:
      "Natural-language questions are converted into structured intent — location, time, and objective — without ever inventing coordinates or dates.",
  },
  {
    title: "Deterministic Risk & Safety",
    description:
      "A transparent, weighted Risk Engine and a fail-closed Safety Guard mean missing or low-confidence data can only ever block a recommendation, never slip through.",
  },
  {
    title: "Fishing Suitability",
    description:
      "ORCA's own suitability scoring — structurally distinct from, and never presented as, an official Potential Fishing Zone advisory.",
  },
  {
    title: "Risk-Aware Routing",
    description:
      "A deterministic A* engine finds routes that minimize distance and environmental risk while respecting every geofence.",
  },
  {
    title: "Resilient Data Pipeline",
    description:
      "A three-tier live → cached → demo fallback keeps the system honestly labeled and functioning even when a source is temporarily unavailable.",
  },
  {
    title: "Grounded, Multilingual Explanations",
    description:
      "Every explanation is checked against the underlying evidence and delivered in English, Hindi, or Kannada.",
  },
];

export function CapabilitiesSection() {
  return (
    <section id="capabilities" className="scroll-mt-20 bg-marine-deep px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-6xl">
        <RevealOnScroll className="max-w-2xl">
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Core Capabilities</p>
          <h2 className="mt-4 text-3xl font-semibold tracking-tight text-marine-white sm:text-5xl">
            Built on a deterministic core, presented through AI.
          </h2>
        </RevealOnScroll>

        <div className="mt-16 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((capability, index) => (
            <RevealOnScroll key={capability.title} delayMs={index * 60}>
              <div className="h-full rounded-2xl border border-marine-cyan/15 bg-marine-ocean/25 p-6 transition-colors hover:border-marine-cyan/35 hover:bg-marine-ocean/35">
                <span className="text-sm font-semibold text-marine-cyan-light">{String(index + 1).padStart(2, "0")}</span>
                <h3 className="mt-3 text-xl font-semibold text-marine-white">{capability.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-marine-white/70">{capability.description}</p>
              </div>
            </RevealOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
