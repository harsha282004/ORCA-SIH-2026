import { useCallback, useEffect, useRef, useState } from "react";

const FRAME_BASE_PATH = "/cinematics/frames";

// Browsers already cap per-origin HTTP/1.1 connections around 6 — matching
// that avoids the loader becoming its own bottleneck while guaranteeing we
// never fire anywhere near 1,200 simultaneous requests.
const MAX_CONCURRENT_LOADS = 6;

// Frames within this many steps of the current scroll target are always
// kept pre-loaded at high priority, so a quick scroll a few frames ahead
// never has to wait on the sequential background fill to reach it.
const PRIORITY_WINDOW = 8;

function frameUrl(frameNumber: number): string {
  // Zero-padded to 4 digits to match the actual files on disk
  // (frame-0001.jpg ... frame-1200.jpg) — never reformatted or guessed.
  return `${FRAME_BASE_PATH}/frame-${String(frameNumber).padStart(4, "0")}.jpg`;
}

export type FrameSequenceStatus = "loading" | "ready" | "error";

export interface FrameSequenceHandle {
  /** The loaded image for `frameNumber`, or null if not loaded (yet) or failed. */
  getFrame: (frameNumber: number) => HTMLImageElement | null;
  /** The nearest loaded frame to `frameNumber` (searching outward both ways), or null if nothing has loaded yet. */
  getNearestFrame: (frameNumber: number) => HTMLImageElement | null;
  /** Moves `frameNumber` and a small window around it to the front of the load queue. */
  prioritize: (frameNumber: number) => void;
}

/**
 * Loads and caches the cinematic JPEG frame sequence
 * (`/cinematics/frames/frame-NNNN.jpg`) without ever creating one `<img>`
 * element per frame in the DOM and without ever firing `totalFrames`
 * simultaneous network requests.
 *
 * Two loading lanes, both drawn from by the SAME bounded concurrency pump:
 * - a priority lane (`prioritize()`): the current scroll target and a small
 *   window around it, always serviced first;
 * - a background lane: every remaining frame walked in strict ascending
 *   NUMERIC order — `Array.from({length}, (_, i) => i + 1)`, never a
 *   lexicographic sort of the filename strings — so the whole sequence
 *   keeps filling in even if the user never scrolls near the end.
 *
 * All loaded/loading/failed bookkeeping lives in refs. The only React
 * state is the one-time "frame 1 is ready" transition (`status`) — no
 * re-render happens per loaded frame, and none happen per scroll tick.
 */
export function useFrameSequence(
  totalFrames: number,
  onFrameLoaded?: (frameNumber: number) => void,
): { handle: FrameSequenceHandle; status: FrameSequenceStatus } {
  const [status, setStatus] = useState<FrameSequenceStatus>("loading");

  const imagesRef = useRef<Array<HTMLImageElement | null>>([]);
  const loadingRef = useRef<Set<number>>(new Set());
  const failedRef = useRef<Set<number>>(new Set());
  const backgroundQueueRef = useRef<number[]>([]);
  const priorityQueueRef = useRef<number[]>([]);
  const inFlightRef = useRef(0);
  const pumpRef = useRef<() => void>(() => {});
  const onFrameLoadedRef = useRef(onFrameLoaded);
  onFrameLoadedRef.current = onFrameLoaded;

  useEffect(() => {
    let cancelled = false;
    imagesRef.current = new Array(totalFrames).fill(null);
    loadingRef.current = new Set();
    failedRef.current = new Set();
    backgroundQueueRef.current = Array.from({ length: totalFrames }, (_, i) => i + 1);
    priorityQueueRef.current = [];
    inFlightRef.current = 0;

    const isSettled = (frameNumber: number) =>
      Boolean(imagesRef.current[frameNumber - 1]) || loadingRef.current.has(frameNumber) || failedRef.current.has(frameNumber);

    const nextFromQueue = (queue: number[]): number | undefined => {
      let candidate = queue.shift();
      while (candidate !== undefined && isSettled(candidate)) candidate = queue.shift();
      return candidate;
    };

    const loadOne = (frameNumber: number) => {
      loadingRef.current.add(frameNumber);
      inFlightRef.current += 1;
      const img = new Image();
      img.onload = () => {
        loadingRef.current.delete(frameNumber);
        inFlightRef.current -= 1;
        if (cancelled) return;
        imagesRef.current[frameNumber - 1] = img;
        if (frameNumber === 1) setStatus("ready");
        onFrameLoadedRef.current?.(frameNumber);
        pump();
      };
      img.onerror = () => {
        // A single missing/broken frame is never fatal — it is recorded as
        // failed (never retried in a loop) and the sequence continues;
        // the renderer falls back to the nearest loaded neighbor for it.
        loadingRef.current.delete(frameNumber);
        inFlightRef.current -= 1;
        if (cancelled) return;
        failedRef.current.add(frameNumber);
        pump();
      };
      img.src = frameUrl(frameNumber);
    };

    const pump = () => {
      if (cancelled) return;
      while (inFlightRef.current < MAX_CONCURRENT_LOADS) {
        const next = nextFromQueue(priorityQueueRef.current) ?? nextFromQueue(backgroundQueueRef.current);
        if (next === undefined) return; // nothing left anywhere
        loadOne(next);
      }
    };

    pumpRef.current = pump;
    pump();

    return () => {
      cancelled = true;
    };
  }, [totalFrames]);

  const getFrame = useCallback((frameNumber: number) => imagesRef.current[frameNumber - 1] ?? null, []);

  const getNearestFrame = useCallback((frameNumber: number) => {
    const images = imagesRef.current;
    if (images.length === 0) return null;
    const clamped = Math.min(Math.max(frameNumber, 1), images.length);
    for (let offset = 0; offset < images.length; offset++) {
      const below = clamped - offset;
      const above = clamped + offset;
      if (below >= 1 && images[below - 1]) return images[below - 1];
      if (above <= images.length && above !== below && images[above - 1]) return images[above - 1];
    }
    return null;
  }, []);

  const prioritize = useCallback((frameNumber: number) => {
    const images = imagesRef.current;
    if (images.length === 0) return;
    const start = Math.max(1, frameNumber - PRIORITY_WINDOW);
    const end = Math.min(images.length, frameNumber + PRIORITY_WINDOW);

    // Closest-first so the EXACT target frame always wins the race for a
    // free load slot.
    const wanted: number[] = [frameNumber];
    for (let d = 1; d <= PRIORITY_WINDOW; d++) {
      if (frameNumber - d >= start) wanted.push(frameNumber - d);
      if (frameNumber + d <= end) wanted.push(frameNumber + d);
    }

    // Prepend the whole (already closest-first) batch in one go — unshifting
    // one at a time would reverse the order, putting the farthest frame at
    // the front instead of the closest.
    const toPrepend = wanted.filter(
      (n) => !images[n - 1] && !loadingRef.current.has(n) && !failedRef.current.has(n) && !priorityQueueRef.current.includes(n),
    );
    if (toPrepend.length > 0) priorityQueueRef.current = [...toPrepend, ...priorityQueueRef.current];
    pumpRef.current();
  }, []);

  const handleRef = useRef<FrameSequenceHandle>({ getFrame, getNearestFrame, prioritize });

  return { handle: handleRef.current, status };
}
