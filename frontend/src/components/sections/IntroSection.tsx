import { RevealOnScroll } from "../common/RevealOnScroll";

// The first stop below the cinematic hero on the warm-sunset-to-deep-blue
// journey — a deep ocean gradient background (never a hard cut) is what
// carries the visual transition; the content itself stays grounded in
// what ORCA actually does (live weather/ocean data, deterministic risk
// scoring, evidence-backed routing), not an unsupported technical claim.
export function IntroSection() {
  return (
    <section className="bg-marine-deep px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">
            Real-Time Ocean Intelligence
          </p>
        </RevealOnScroll>

        <RevealOnScroll delayMs={80}>
          <h2 className="mt-6 max-w-4xl text-3xl font-semibold leading-[1.1] tracking-tight text-marine-white sm:text-5xl lg:text-6xl">
            Navigate Smarter.
            <br />
            Sail Safer.
          </h2>
        </RevealOnScroll>

        <RevealOnScroll delayMs={160}>
          <p className="mt-10 max-w-2xl text-balance text-base leading-relaxed text-marine-white/70 sm:text-lg">
            ORCA — Marine EcOsystem Reasoning with Collaborative Agents — fuses live weather, ocean, hazard, and
            boundary data behind a single conversational interface, reasons across space and time under a
            deterministic safety layer, and returns an explainable, evidence-backed recommendation instead of a
            wall of raw numbers.
          </p>
        </RevealOnScroll>
      </div>
    </section>
  );
}
