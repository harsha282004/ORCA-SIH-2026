import { useEffect, useRef } from "react";

type ProgressListener = (progress: number) => void;

export interface CinematicScrollHandle {
  /** Current DISPLAYED (smoothed) progress (0..1), readable at any time without a re-render. */
  progressRef: React.RefObject<number>;
  /** Register a listener called whenever the smoothed progress changes. Returns an unsubscribe function. */
  subscribe: (listener: ProgressListener) => () => void;
}

function clamp01(value: number): number {
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

// --- Smoothing parameters -------------------------------------------------
//
// The raw scroll-derived value (`targetProgress`) jumps directly to wherever
// the browser's scroll position currently is — for a fast wheel/trackpad
// flick that can be a large delta between two consecutive animation frames,
// which reads as a hard "jump cut" rather than a scrub. `displayProgress`
// instead chases `targetProgress` via exponential decay, so the two-clip
// video timeline always moves through intermediate positions instead of
// snapping to a new one.
//
// Exponential decay (not a fixed `+= (target - display) * k` per frame) is
// used specifically because a fixed-factor lerp is framerate-dependent —
// the same factor produces a different real-world speed at 60Hz vs 120Hz,
// or after a dropped frame. Framing it as a time constant keeps the feel
// identical regardless of display refresh rate. This is the ONE controlled
// animation loop for the whole cinematic hero — video seeking, the 3D
// depth transform, and the progressive text reveal all subscribe to the
// same smoothed value rather than running independent loops.

// Time constant (ms) for the exponential chase — after this many
// milliseconds the gap to the target has shrunk by ~63%. Empirically tuned
// (see docs in the project's QA history): low enough that response to a
// fresh scroll input is immediate, high enough to visibly smooth out the
// per-frame jaggedness of raw scroll deltas.
const SMOOTHING_TIME_CONSTANT_MS = 90;

// Once the gap between displayed and target progress is smaller than this,
// snap exactly to the target and stop scheduling further animation frames.
const SETTLE_THRESHOLD = 0.0006;

// Caps the per-frame delta-time fed into the decay calculation, guarding
// against a single huge "catch-up" jump if the tab was backgrounded or the
// main thread was blocked for a while.
const MAX_FRAME_DELTA_MS = 50;

// Fallback dt for the very first smoothing frame (no previous timestamp yet).
const DEFAULT_FRAME_DELTA_MS = 1000 / 60;

/**
 * Tracks how far the viewport has scrolled through a tall "track" element,
 * as a smoothed 0..1 progress value — the single source of truth behind
 * the two-clip scroll-scrubbed cinematic sequence.
 *
 * Two rAF-driven mechanisms, both self-terminating (neither runs forever):
 * 1. A scroll/resize listener, coalesced to at most once per frame, that
 *    recomputes the raw scroll-derived `targetProgress`.
 * 2. A short-lived smoothing loop, started only when `targetProgress` is
 *    meaningfully ahead of the displayed value, that steps `displayProgress`
 *    toward it each frame and stops scheduling itself once settled.
 *
 * Deliberately avoids React state throughout: progress updates are pushed
 * to plain-function listeners (which mutate the DOM/video elements
 * directly) instead of triggering re-renders, so a busy scroll gesture
 * never causes React reconciliation.
 */
export function useCinematicScroll(trackRef: React.RefObject<HTMLElement | null>, enabled: boolean): CinematicScrollHandle {
  const targetProgressRef = useRef(0);
  const displayProgressRef = useRef(0);
  const listenersRef = useRef(new Set<ProgressListener>());
  const scrollRafIdRef = useRef<number | null>(null);
  const smoothingRafIdRef = useRef<number | null>(null);
  const lastFrameTimeRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const track = trackRef.current;
    if (!track) return;

    const emit = (value: number) => {
      displayProgressRef.current = value;
      for (const listener of listenersRef.current) listener(value);
    };

    const ensureSmoothingLoop = () => {
      if (smoothingRafIdRef.current !== null) return; // already chasing the target
      if (Math.abs(targetProgressRef.current - displayProgressRef.current) < SETTLE_THRESHOLD) return; // already there
      lastFrameTimeRef.current = null;
      smoothingRafIdRef.current = requestAnimationFrame(smoothingStep);
    };

    const smoothingStep = (timestampMs: number) => {
      const target = targetProgressRef.current;
      const dt =
        lastFrameTimeRef.current === null
          ? DEFAULT_FRAME_DELTA_MS
          : Math.min(timestampMs - lastFrameTimeRef.current, MAX_FRAME_DELTA_MS);
      lastFrameTimeRef.current = timestampMs;

      const decay = 1 - Math.exp(-dt / SMOOTHING_TIME_CONSTANT_MS);
      const next = displayProgressRef.current + (target - displayProgressRef.current) * decay;

      if (Math.abs(target - next) < SETTLE_THRESHOLD) {
        emit(target); // snap exactly — no permanent asymptotic residue
        smoothingRafIdRef.current = null;
        lastFrameTimeRef.current = null;
        return; // settled: no further frame is scheduled
      }

      emit(next);
      smoothingRafIdRef.current = requestAnimationFrame(smoothingStep);
    };

    const computeTarget = () => {
      scrollRafIdRef.current = null;
      const rect = track.getBoundingClientRect();
      const scrollableDistance = rect.height - window.innerHeight;

      // The track is shorter than one viewport (shouldn't happen with the
      // configured scroll multiplier, but never divide by zero/negative).
      const next = scrollableDistance <= 0 ? (rect.top <= 0 ? 1 : 0) : clamp01(-rect.top / scrollableDistance);

      targetProgressRef.current = next;
      ensureSmoothingLoop();
    };

    const requestScrollTick = () => {
      if (scrollRafIdRef.current !== null) return;
      scrollRafIdRef.current = requestAnimationFrame(computeTarget);
    };

    // Establish the correct position immediately on mount (e.g. a refresh
    // mid-page) — a direct snap, never an animated glide-in from zero, so
    // there is no visual jump when the browser restores scroll position.
    computeTarget();
    displayProgressRef.current = targetProgressRef.current;
    emit(displayProgressRef.current);

    window.addEventListener("scroll", requestScrollTick, { passive: true });
    window.addEventListener("resize", requestScrollTick);

    return () => {
      window.removeEventListener("scroll", requestScrollTick);
      window.removeEventListener("resize", requestScrollTick);
      if (scrollRafIdRef.current !== null) cancelAnimationFrame(scrollRafIdRef.current);
      if (smoothingRafIdRef.current !== null) cancelAnimationFrame(smoothingRafIdRef.current);
      scrollRafIdRef.current = null;
      smoothingRafIdRef.current = null;
    };
  }, [trackRef, enabled]);

  const subscribe = (listener: ProgressListener) => {
    listenersRef.current.add(listener);
    return () => listenersRef.current.delete(listener);
  };

  return { progressRef: displayProgressRef, subscribe };
}
