import { Compass, Radar, ShieldCheck, Users } from "lucide-react";

import { RevealOnScroll } from "../common/RevealOnScroll";

// Each card maps to a real, implemented capability — phrased under the
// requested marine themes, never a claim ORCA doesn't back up (e.g.
// "Cleaner Oceans" describes geofence/suitability-driven guidance ORCA
// genuinely computes, not an ecological-monitoring feature it doesn't have).
const FEATURES = [
  {
    icon: Radar,
    title: "Real-time Insights",
    description: "Live weather and ocean data, interpreted for the question you actually asked.",
  },
  {
    icon: Compass,
    title: "Safer Voyages",
    description: "Deterministic, risk-aware routing that respects every geofence — never a straight line pretending to be safe.",
  },
  {
    icon: ShieldCheck,
    title: "Cleaner Oceans",
    description: "Fishing-suitability guidance that keeps protected zones and marine boundaries out of the recommendation, not just the fine print.",
  },
  {
    icon: Users,
    title: "Stronger Communities",
    description: "Grounded explanations in English, Hindi, or Kannada — for fishermen, researchers, and coastal authorities alike.",
  },
];

export function FeatureCardsSection() {
  return (
    <section className="bg-marine-deep px-6 py-24 sm:px-10 sm:py-32 lg:px-16">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, description }, index) => (
            <RevealOnScroll key={title} delayMs={index * 80}>
              <div className="h-full rounded-2xl border border-marine-cyan/15 bg-marine-ocean/45 p-6 backdrop-blur-sm">
                <Icon className="h-6 w-6 text-marine-cyan-light" strokeWidth={1.5} aria-hidden="true" />
                <h3 className="mt-5 text-lg font-semibold text-marine-white">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-marine-white/65">{description}</p>
              </div>
            </RevealOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
