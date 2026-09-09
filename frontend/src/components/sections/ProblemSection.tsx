import { RevealOnScroll } from "../common/RevealOnScroll";

const SIGNALS = ["Environment", "Location", "Conditions", "Risk", "Available intelligence"];

// Theme correction (task §5): explicitly required as a LIGHT ocean/off-
// white section — was bg-marine-ocean (dark), the second dark section in a
// row after the hero+intro, part of the "everything dark" problem.
export function ProblemSection() {
  return (
    <section className="bg-marine-surface-alt px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-blue">The Maritime Problem</p>
          <h2 className="mt-4 text-4xl font-semibold uppercase tracking-tight text-marine-ink sm:text-6xl lg:text-7xl">
            The ocean is complex.
          </h2>
        </RevealOnScroll>

        <div className="mt-12 grid gap-12 lg:grid-cols-2 lg:gap-20">
          <RevealOnScroll delayMs={100}>
            <p className="text-base leading-relaxed text-marine-ink-muted sm:text-lg">
              A single maritime decision depends on more than any one source can tell you. Weather forecasts,
              wave and wind conditions, marine hazards, restricted zones, and fishing-suitability signals all
              live in disconnected systems — and none of them, alone, answers the question a person actually
              has.
            </p>
            <p className="mt-6 text-base font-medium leading-relaxed text-marine-ink">ORCA brings these signals together.</p>
          </RevealOnScroll>

          <RevealOnScroll delayMs={200}>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-2">
              {SIGNALS.map((signal, index) => (
                <li
                  key={signal}
                  className="rounded-xl border border-marine-border bg-marine-surface px-4 py-4 text-marine-ink shadow-sm"
                >
                  <span className="text-xs text-marine-blue">{String(index + 1).padStart(2, "0")}</span>
                  <p className="mt-1 text-base font-medium sm:text-lg">{signal}</p>
                </li>
              ))}
            </ul>
          </RevealOnScroll>
        </div>
      </div>
    </section>
  );
}
