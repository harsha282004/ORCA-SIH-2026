import { RevealOnScroll } from "../common/RevealOnScroll";

// Theme correction: this was the section the reported "huge dark-blue
// empty area under 'Navigate Smarter. Sail Safer.'" complaint pointed at —
// it followed the dark cinematic hero with ANOTHER full dark-navy section,
// so the page read as one continuous dark surface from the very top. This
// is now the landing page's first deliberate LIGHT section — the strongest
// possible contrast statement right where a visitor's eye lands first
// after the hero hands off, using pale aqua/off-white with dark-navy text.
export function IntroSection() {
  return (
    <section className="bg-marine-mist px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">
            Real-Time Ocean Intelligence
          </p>
        </RevealOnScroll>

        <RevealOnScroll delayMs={80}>
          <h2 className="mt-6 max-w-4xl text-3xl font-semibold leading-[1.1] tracking-tight text-marine-ink sm:text-5xl lg:text-6xl">
            Navigate Smarter.
            <br />
            Sail Safer.
          </h2>
        </RevealOnScroll>

        <RevealOnScroll delayMs={160}>
          <p className="mt-10 max-w-2xl text-balance text-base leading-relaxed text-marine-ink-muted sm:text-lg">
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
