import { RevealOnScroll } from "../common/RevealOnScroll";

const SIGNALS = ["Environment", "Location", "Conditions", "Risk", "Available intelligence"];

export function ProblemSection() {
  return (
    <section className="bg-marine-ocean px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">The Maritime Problem</p>
          <h2 className="mt-4 text-4xl font-semibold uppercase tracking-tight text-marine-white sm:text-6xl lg:text-7xl">
            The ocean is complex.
          </h2>
        </RevealOnScroll>

        <div className="mt-12 grid gap-12 lg:grid-cols-2 lg:gap-20">
          <RevealOnScroll delayMs={100}>
            <p className="text-base leading-relaxed text-marine-white/70 sm:text-lg">
              A single maritime decision depends on more than any one source can tell you. Weather forecasts,
              wave and wind conditions, marine hazards, restricted zones, and fishing-suitability signals all
              live in disconnected systems — and none of them, alone, answers the question a person actually
              has.
            </p>
            <p className="mt-6 text-base font-medium leading-relaxed text-marine-white">ORCA brings these signals together.</p>
          </RevealOnScroll>

          <RevealOnScroll delayMs={200}>
            <ul className="space-y-0 border-t border-marine-cyan/15">
              {SIGNALS.map((signal, index) => (
                <li
                  key={signal}
                  className="flex items-baseline justify-between border-b border-marine-cyan/15 py-4 text-marine-white"
                >
                  <span className="text-sm text-marine-white/50">{String(index + 1).padStart(2, "0")}</span>
                  <span className="text-lg font-medium sm:text-xl">{signal}</span>
                </li>
              ))}
            </ul>
          </RevealOnScroll>
        </div>
      </div>
    </section>
  );
}
