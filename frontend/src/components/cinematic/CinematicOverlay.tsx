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

// Each hero text element fades in over its own short window of overall
// cinematic progress and then holds — a progressive build-up (eyebrow ->
// headline -> description -> CTA) rather than everything appearing at
// once, per the requested "chapters" pacing. All four fade back out
// together during the hero's own end transition (CINEMATIC_TRANSITION_START).
const EYEBROW_RANGE: [number, number] = [0.0, 0.06];
const HEADLINE_RANGE: [number, number] = [0.08, 0.2];
const DESCRIPTION_RANGE: [number, number] = [0.24, 0.36];
const CTA_RANGE: [number, number] = [0.4, 0.52];

export function CinematicOverlay({ scrollHandle, reducedMotion }: CinematicOverlayProps) {
  const eyebrowRef = useRef<HTMLParagraphElement | null>(null);
  const headlineRef = useRef<HTMLHeadingElement | null>(null);
  const descriptionRef = useRef<HTMLParagraphElement | null>(null);
  const ctaRef = useRef<HTMLDivElement | null>(null);
  const scrollHintRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (reducedMotion) return;

    const applyReveal = (el: HTMLElement | null, revealAmount: number) => {
      if (!el) return;
      el.style.opacity = String(revealAmount);
      el.style.transform = `translateY(${(1 - revealAmount) * 16}px)`;
    };

    const unsubscribe = scrollHandle.subscribe((progress) => {
      // All four elements fade back out together during the hero's own
      // hand-off transition, so the text never overlaps the next section.
      const endFade = 1 - rangeProgress(progress, CINEMATIC_TRANSITION_START, 1);

      applyReveal(eyebrowRef.current, rangeProgress(progress, ...EYEBROW_RANGE) * endFade);
      applyReveal(headlineRef.current, rangeProgress(progress, ...HEADLINE_RANGE) * endFade);
      applyReveal(descriptionRef.current, rangeProgress(progress, ...DESCRIPTION_RANGE) * endFade);
      applyReveal(ctaRef.current, rangeProgress(progress, ...CTA_RANGE) * endFade);

      if (scrollHintRef.current) {
        scrollHintRef.current.style.opacity = String(clamp01(1 - progress * 12));
      }
    });

    return unsubscribe;
  }, [scrollHandle, reducedMotion]);

  const staticStyle = reducedMotion ? { opacity: 1, transform: "none" } : { opacity: 0, transform: "translateY(16px)" };

  return (
    <div className="pointer-events-none absolute inset-0 flex flex-col justify-end p-6 sm:p-10 lg:p-16">
      <div className="max-w-3xl">
        <p
          ref={eyebrowRef}
          style={staticStyle}
          className="mb-5 text-xs font-medium uppercase tracking-[0.35em] text-orca-mint"
        >
          Ocean Intelligence for a Safer Tomorrow
        </p>
        <h1
          ref={headlineRef}
          style={staticStyle}
          className="max-w-4xl text-4xl font-semibold leading-[1.05] tracking-tight text-orca-cream sm:text-6xl lg:text-7xl"
        >
          Safer Oceans.
          <br />
          Stronger Communities.
        </h1>
        <p
          ref={descriptionRef}
          style={staticStyle}
          className="mt-7 max-w-xl text-balance text-base leading-relaxed text-orca-cream/80 sm:text-lg"
        >
          AI-powered insights for safer routes, real-time risk awareness, and evidence-backed maritime decisions —
          for fishermen, researchers, and coastal authorities.
        </p>
        <div ref={ctaRef} style={staticStyle} className="mt-9 flex flex-wrap items-center gap-4">
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
