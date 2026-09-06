import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { useCinematicScroll } from "../../hooks/useCinematicScroll";
import { CINEMATIC_SCROLL_HEIGHT_VH, CINEMATIC_TRANSITION_START } from "../../lib/cinematic";
import { CinematicFrameSequence, type CinematicFrameSequenceStatus } from "./CinematicFrameSequence";
import { CinematicOverlay } from "./CinematicOverlay";

// Width below which the 3D depth effect is scaled down — a full-strength
// tilt/zoom reads as heavier on a small screen held close to the face.
const MOBILE_BREAKPOINT_PX = 768;

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function rangeProgress(value: number, start: number, end: number): number {
  if (end <= start) return value >= end ? 1 : 0;
  return clamp01((value - start) / (end - start));
}

export function CinematicHero() {
  const trackRef = useRef<HTMLElement | null>(null);
  const stickyRef = useRef<HTMLDivElement | null>(null);
  const frameLayerRef = useRef<HTMLDivElement | null>(null);
  const transitionFadeRef = useRef<HTMLDivElement | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const scrollHandle = useCinematicScroll(trackRef, !reducedMotion);
  const [frameStatus, setFrameStatus] = useState<CinematicFrameSequenceStatus>("loading");

  useEffect(() => {
    if (reducedMotion) return;

    const unsubscribe = scrollHandle.subscribe((progress) => {
      const isMobile = window.innerWidth < MOBILE_BREAKPOINT_PX;
      const intensity = isMobile ? 0.4 : 1;

      // Subtle zoom-in + tilt settle over the first 15% of the sequence.
      const introSettle = 1 - rangeProgress(progress, 0, 0.15);
      const introScale = 1 + introSettle * 0.05 * intensity;
      const rotateX = introSettle * 2 * intensity;

      // A gentle continuous upward drift for a constant sense of depth.
      const translateY = progress * -24 * intensity;

      if (frameLayerRef.current) {
        frameLayerRef.current.style.transform = `perspective(1200px) scale(${introScale}) rotateX(${rotateX}deg) translateY(${translateY}px)`;
      }

      const transitionAmount = rangeProgress(progress, CINEMATIC_TRANSITION_START, 1);
      if (stickyRef.current) {
        stickyRef.current.style.filter = `brightness(${1 - transitionAmount * 0.45}) blur(${transitionAmount * 3}px)`;
      }
      if (transitionFadeRef.current) {
        transitionFadeRef.current.style.opacity = String(transitionAmount);
      }
    });

    return unsubscribe;
  }, [scrollHandle, reducedMotion]);

  return (
    <section
      ref={trackRef}
      style={{ height: reducedMotion ? "100vh" : `${CINEMATIC_SCROLL_HEIGHT_VH}vh` }}
      className="relative"
      aria-label="ORCA cinematic introduction"
    >
      <div
        ref={stickyRef}
        className={
          reducedMotion
            ? "relative h-screen w-full overflow-hidden bg-orca-deep"
            : "sticky top-0 h-screen w-full overflow-hidden bg-orca-deep"
        }
      >
        <div ref={frameLayerRef} className="absolute inset-0 h-full w-full">
          {/* Base fallback — always present; the visible surface while the
              first frame is still loading or if the sequence fails outright.
              Deep-teal-based (not a generic dark-blue tech gradient) to
              match the ORCA coastal palette even when no frame is showing. */}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(134,210,179,0.18),_transparent_60%),linear-gradient(to_bottom,_#0d211c,_#183831_55%,_#0d211c)]" />

          {frameStatus !== "error" && (
            <CinematicFrameSequence
              scrollHandle={scrollHandle}
              reducedMotion={reducedMotion}
              onStatusChange={setFrameStatus}
              className={`absolute inset-0 h-full w-full transition-opacity duration-700 ${frameStatus === "ready" ? "opacity-100" : "opacity-0"}`}
            />
          )}

          {frameStatus === "loading" && (
            <div className="absolute inset-x-0 bottom-10 flex justify-center sm:bottom-14" aria-hidden="true">
              <span className="text-[11px] font-medium uppercase tracking-[0.3em] text-orca-cream/60">
                Loading cinematic experience…
              </span>
            </div>
          )}
        </div>

        {/* Dark overlay — deep-teal-tinted (not generic black) for contrast without erasing the cinematic's impact. */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-orca-deep/50 via-transparent to-orca-deep/85" />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-orca-deep/30 via-transparent to-orca-deep/30" />

        <CinematicOverlay scrollHandle={scrollHandle} reducedMotion={reducedMotion} />

        {/* Cinematic end transition — fades the warm-sunset hero into the
            DEEP-MARINE page background below (IntroSection's "Real-Time
            Ocean Intelligence" section, #0A2540) rather than a hard cut —
            the one color this decorative hand-off overlay uses is the only
            part of CinematicHero touched for the marine-theme migration;
            the frame sequence/canvas/scroll-mapping/interpolation below are
            unchanged. */}
        <div
          ref={transitionFadeRef}
          className="pointer-events-none absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-marine-deep via-marine-deep/70 to-transparent opacity-0"
        />
      </div>
    </section>
  );
}
