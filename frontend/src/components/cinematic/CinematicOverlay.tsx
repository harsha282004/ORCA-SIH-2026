import { useEffect, useRef } from "react";
import { ArrowRight, Compass } from "lucide-react";
import { Link } from "react-router-dom";

import type { CinematicScrollHandle } from "../../hooks/useCinematicScroll";
import { CINEMATIC_TRANSITION_START } from "../../lib/cinematic";

interface CinematicOverlayProps {
  scrollHandle: CinematicScrollHandle;
  reducedMotion: boolean;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Linear 0..1 ramp between [start, end], clamped outside that range. */
function rangeProgress(value: number, start: number, end: number): number {
  if (end <= start) return value >= end ? 1 : 0;
  return clamp01((value - start) / (end - start));
}

// Phase 10 redesign: the branding/headline used to be INVISIBLE at
// progress=0 (each element's own reveal range started above 0, e.g. the
// eyebrow needed 0-6% scroll before showing at all) — a real gap against
// "when the website initially loads, place ORCA branding on the left
// side," reproduced live (a fresh page load showed only the nav bar over
// the coastal image, no heading, until the visitor scrolled). The text now
// enters via a short staggered fade-in driven directly on mount (below),
// so it is legible immediately with NO scroll required. A CSS keyframe
// class was deliberately NOT used here: `animation-fill-mode: both/
// forwards` keeps overriding an element's opacity for as long as the
// animation stays attached, which would fight the scroll-driven end-fade
// below (inline styles lose that cascade battle to a still-attached
// animation). Plain inline-style transitions have no such conflict — the
// same imperative style this file already uses for the scroll handler.
const STAGGER_DELAY_MS = [0, 150, 300, 450];
const ENTRANCE_TRANSITION = "opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)";

export function CinematicOverlay({ scrollHandle, reducedMotion }: CinematicOverlayProps) {
  const eyebrowRef = useRef<HTMLParagraphElement | null>(null);
  const headlineRef = useRef<HTMLHeadingElement | null>(null);
  const descriptionRef = useRef<HTMLParagraphElement | null>(null);
  const ctaRef = useRef<HTMLDivElement | null>(null);
  const scrollHintRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (reducedMotion) return;

    const elements = [eyebrowRef.current, headlineRef.current, descriptionRef.current, ctaRef.current];
    const timers = elements.map((el, i) =>
      window.setTimeout(() => {
        if (!el) return;
        el.style.transition = ENTRANCE_TRANSITION;
        el.style.opacity = "1";
        el.style.transform = "translateY(0px)";
      }, STAGGER_DELAY_MS[i]),
    );

    const applyEndFade = (el: HTMLElement | null, endFade: number) => {
      if (!el) return;
      // Only ever DAMPENS opacity for the hand-off transition — the mount
      // entrance above already brought it to 1, so a fresh page load is
      // never gated behind a scroll gesture.
      el.style.opacity = String(endFade);
    };

    const unsubscribe = scrollHandle.subscribe((progress) => {
      const endFade = 1 - rangeProgress(progress, CINEMATIC_TRANSITION_START, 1);

      applyEndFade(eyebrowRef.current, endFade);
      applyEndFade(headlineRef.current, endFade);
      applyEndFade(descriptionRef.current, endFade);
      applyEndFade(ctaRef.current, endFade);

      if (scrollHintRef.current) {
        scrollHintRef.current.style.opacity = String(clamp01(1 - progress * 12));
      }
    });

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      unsubscribe();
    };
  }, [scrollHandle, reducedMotion]);

  const initialStyle = reducedMotion ? { opacity: 1, transform: "none" } : { opacity: 0, transform: "translateY(16px)" };

  return (
    <div className="pointer-events-none absolute inset-0 flex flex-col justify-end p-6 sm:p-10 lg:p-16">
      <div className="max-w-3xl">
        <p
          ref={eyebrowRef}
          style={initialStyle}
          className="mb-5 text-xs font-medium uppercase tracking-[0.35em] text-orca-mint"
        >
          ORCA — Ocean Intelligence for a Safer Tomorrow
        </p>
        <h1
          ref={headlineRef}
          style={initialStyle}
          className="max-w-4xl text-4xl font-semibold leading-[1.05] tracking-tight text-orca-cream sm:text-6xl lg:text-7xl"
        >
          Safer Oceans.
          <br />
          Stronger Communities.
        </h1>
        <p
          ref={descriptionRef}
          style={initialStyle}
          className="mt-7 max-w-xl text-balance text-base leading-relaxed text-orca-cream/80 sm:text-lg"
        >
          AI-powered insights for safer routes, real-time risk awareness, and evidence-backed maritime decisions —
          for fishermen, researchers, and coastal authorities.
        </p>
        <div ref={ctaRef} style={initialStyle} className="mt-9 flex flex-wrap items-center gap-4">
          <Link
            to="/ask-orca"
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full bg-orca-teal-strong px-6 py-3 text-sm font-semibold text-orca-cream transition-colors hover:bg-orca-mint hover:text-orca-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orca-mint focus-visible:ring-offset-2 focus-visible:ring-offset-orca-deep"
          >
            Ask ORCA <ArrowRight className="h-4 w-4" strokeWidth={2} />
          </Link>
          <Link
            to="/route-planner"
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-orca-cream/40 px-6 py-3 text-sm font-semibold text-orca-cream transition-colors hover:border-orca-cream hover:bg-orca-cream/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orca-cream focus-visible:ring-offset-2 focus-visible:ring-offset-orca-deep"
          >
            <Compass className="h-4 w-4" strokeWidth={2} /> Plan a Route
          </Link>
        </div>
      </div>

      {!reducedMotion && (
        <div
          ref={scrollHintRef}
          className="absolute bottom-10 right-6 flex flex-col items-center gap-2 text-orca-cream/70 sm:right-10 lg:right-16"
          aria-hidden="true"
        >
          <span className="text-[11px] font-medium uppercase tracking-[0.3em]">Scroll to explore</span>
          <span className="h-8 w-px bg-gradient-to-b from-orca-cream/70 to-transparent" />
        </div>
      )}
    </div>
  );
}
