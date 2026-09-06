import { useEffect, useState } from "react";

/**
 * Reports whether the page has scrolled past `thresholdPx` — used to
 * switch the navigation bar from transparent-over-hero to a solid/glass
 * background. Only re-renders when the boolean actually flips (typically
 * twice per scroll session), not on every scroll tick.
 */
export function useScrolledPast(thresholdPx: number): boolean {
  const [scrolledPast, setScrolledPast] = useState(() => (typeof window === "undefined" ? false : window.scrollY > thresholdPx));

  useEffect(() => {
    let ticking = false;

    const handleScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        setScrolledPast((prev) => {
          const next = window.scrollY > thresholdPx;
          return prev === next ? prev : next;
        });
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [thresholdPx]);

  return scrolledPast;
}
