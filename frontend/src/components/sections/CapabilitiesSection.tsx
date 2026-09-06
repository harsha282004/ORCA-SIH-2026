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

        <div className="mt-16 divide-y divide-marine-cyan/10 border-t border-marine-cyan/10">
          {CAPABILITIES.map((capability, index) => (
            <RevealOnScroll key={capability.title} delayMs={index * 60}>
              <div className="grid gap-3 py-8 sm:grid-cols-[100px_1fr] sm:gap-8">
                <span className="text-sm text-marine-cyan-light sm:text-base">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <h3 className="text-xl font-semibold text-marine-white sm:text-2xl">{capability.title}</h3>
                  <p className="mt-2 max-w-2xl text-sm leading-relaxed text-marine-white/70 sm:text-base">
                    {capability.description}
                  </p>
                </div>
              </div>
            </RevealOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
