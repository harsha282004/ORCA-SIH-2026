import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { RevealOnScroll } from "../common/RevealOnScroll";

// The deepest, calmest point of the page — a darker, quieter marine
// gradient than every section above it, closing the "sunset -> deep
// ocean" journey the cinematic hero begins.
export function FinalCtaSection() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-b from-marine-ocean to-[#061A2E] px-6 py-28 text-center sm:py-40">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,_rgba(56,189,248,0.10),_transparent_60%)]"
        aria-hidden="true"
      />
      <RevealOnScroll className="relative mx-auto max-w-2xl">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Safer Oceans, Sustainable Tomorrow</p>
        <h2 className="mt-5 text-3xl font-semibold tracking-tight text-marine-white sm:text-6xl">Ready to explore ORCA?</h2>
        <p className="mx-auto mt-5 max-w-lg text-balance text-base leading-relaxed text-marine-white/80 sm:text-lg">
          Turn fragmented coastal data into an intelligent, evidence-backed decision.
        </p>
        <Link
          to="/ask-orca"
          className="mt-9 inline-flex items-center gap-2 rounded-full bg-marine-cyan px-7 py-3.5 text-sm font-semibold text-marine-deep transition-colors hover:bg-marine-cyan-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan-light focus-visible:ring-offset-2 focus-visible:ring-offset-marine-ocean"
        >
          Open ORCA <ArrowRight className="h-4 w-4" strokeWidth={2} />
        </Link>
      </RevealOnScroll>
    </section>
  );
}
