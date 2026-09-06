import { useEffect, useRef } from "react";

import type { CinematicScrollHandle } from "../../hooks/useCinematicScroll";
import { useFrameSequence } from "../../hooks/useFrameSequence";
import { TOTAL_CINEMATIC_FRAMES } from "../../lib/cinematic";

export type CinematicFrameSequenceStatus = "loading" | "ready" | "error";

interface CinematicFrameSequenceProps {
  scrollHandle: CinematicScrollHandle;
  reducedMotion: boolean;
  onStatusChange?: (status: CinematicFrameSequenceStatus) => void;
  className?: string;
}

// Source frames are 1280x720 (16:9) — see public/cinematics/frames/.
// (Kept for documentation; drawCover reads the real decoded size from each
// image directly rather than assuming it.)

// The fixed 720p source material has no more real detail to gain past
// ~2x device pixel ratio — capping it keeps the canvas backing buffer (and
// therefore every draw call) bounded on 3x "retina" phones instead of
// scaling cost for pixels the source frames can't actually provide.
const MAX_DEVICE_PIXEL_RATIO = 2;

function frameNumberForProgress(progress: number): number {
  // progress 0 -> frame 1, progress 1 -> frame TOTAL_CINEMATIC_FRAMES,
  // linear in between, rounded to the nearest whole frame.
  const raw = 1 + progress * (TOTAL_CINEMATIC_FRAMES - 1);
  return Math.min(TOTAL_CINEMATIC_FRAMES, Math.max(1, Math.round(raw)));
}

/** CSS `object-fit: cover` equivalent for canvas: fills the destination
 * rect completely, preserving the source's own aspect ratio, cropping
 * whichever axis overflows — never stretching, never letterboxing. */
function drawCover(ctx: CanvasRenderingContext2D, img: HTMLImageElement, destWidth: number, destHeight: number): void {
  const imgRatio = img.naturalWidth / img.naturalHeight;
  const destRatio = destWidth / destHeight;

  let sx: number;
  let sy: number;
  let sWidth: number;
  let sHeight: number;

  if (imgRatio > destRatio) {
    // Source is relatively wider than the destination -> crop its sides.
    sHeight = img.naturalHeight;
    sWidth = sHeight * destRatio;
    sx = (img.naturalWidth - sWidth) / 2;
    sy = 0;
  } else {
    // Source is relatively taller than the destination -> crop top/bottom.
    sWidth = img.naturalWidth;
    sHeight = sWidth / destRatio;
    sx = 0;
    sy = (img.naturalHeight - sHeight) / 2;
  }

  ctx.drawImage(img, sx, sy, sWidth, sHeight, 0, 0, destWidth, destHeight);
}

/**
 * Renders the 1,200-frame cinematic JPEG sequence to a `<canvas>`, driven
 * by the SAME smoothed scroll progress (`useCinematicScroll`) the old
 * two-clip video timeline used — scroll progress (0..1) maps directly to a
 * target frame (1..1,200); the hook's own exponential-decay smoothing
 * already makes that mapping glide between frames rather than snapping, so
 * this component adds no second interpolation/animation loop of its own —
 * drawing happens synchronously inside the scroll hook's existing
 * per-tick callback, imperatively (refs + canvas), with zero React state
 * updates per frame and zero re-renders per scroll tick.
 */
export function CinematicFrameSequence({ scrollHandle, reducedMotion, onStatusChange, className }: CinematicFrameSequenceProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastTargetFrameRef = useRef(1);
  const lastDrawnFrameRef = useRef<number | null>(null);
  const drawRef = useRef<(frameNumber: number) => void>(() => {});

  const { handle, status } = useFrameSequence(TOTAL_CINEMATIC_FRAMES, (loadedFrameNumber) => {
    // A background/priority load just finished for the frame currently
    // being requested — if the user is stationary (no further scroll
    // ticks to naturally trigger a redraw), show it now instead of
    // waiting for the next scroll event.
    if (loadedFrameNumber === lastTargetFrameRef.current) drawRef.current(loadedFrameNumber);
  });

  const draw = (frameNumber: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const image = handle.getFrame(frameNumber) ?? handle.getNearestFrame(frameNumber);
    if (!image) return; // nothing loaded yet at all — keep the atmospheric fallback background visible

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawCover(ctx, image, canvas.width, canvas.height);
    lastDrawnFrameRef.current = frameNumber;
  };
  drawRef.current = draw;

  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

  // --- Canvas sizing (responsive, DPR-correct) --------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const displayWidth = parent.clientWidth;
      const displayHeight = parent.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO);
      const bufferWidth = Math.round(displayWidth * dpr);
      const bufferHeight = Math.round(displayHeight * dpr);

      if (canvas.width !== bufferWidth || canvas.height !== bufferHeight) {
        canvas.width = bufferWidth;
        canvas.height = bufferHeight;
      }
      canvas.style.width = `${displayWidth}px`;
      canvas.style.height = `${displayHeight}px`;

      // Re-draw whatever frame was last showing at the new canvas size —
      // a resize must never leave the canvas blank or stretched.
      if (lastDrawnFrameRef.current !== null) drawRef.current(lastDrawnFrameRef.current);
    };

    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // --- Initial frame ------------------------------------------------------
  useEffect(() => {
    // Frame 1 is requested at the highest priority regardless of
    // `reducedMotion` — it is the first thing any visitor sees, scroll-
    // driven or not.
    handle.prioritize(1);
    drawRef.current(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Scroll-driven frame selection -------------------------------------
  useEffect(() => {
    if (reducedMotion) return; // a single static frame only — no scroll subscription at all

    const unsubscribe = scrollHandle.subscribe((progress) => {
      const frameNumber = frameNumberForProgress(progress);
      lastTargetFrameRef.current = frameNumber;
      if (frameNumber === lastDrawnFrameRef.current) return; // already showing this exact frame
      handle.prioritize(frameNumber);
      drawRef.current(frameNumber);
    });

    return unsubscribe;
  }, [scrollHandle, reducedMotion, handle]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
