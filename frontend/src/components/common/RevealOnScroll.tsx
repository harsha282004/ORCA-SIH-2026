import { useEffect, useRef, useState, type ReactNode } from "react";

import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

interface RevealOnScrollProps {
  children: ReactNode;
  className?: string;
  delayMs?: number;
}

/**
 * Fades + lifts content into place the first time it enters the viewport.
 * Uses a single IntersectionObserver per element (cheap, native, no scroll
 * listener) and renders content fully visible immediately when the user
 * prefers reduced motion.
 */
export function RevealOnScroll({ children, className = "", delayMs = 0 }: RevealOnScrollProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (reducedMotion) {
      setVisible(true);
      return;
    }
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [reducedMotion]);

  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-out ${visible ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"} ${className}`}
      style={{ transitionDelay: visible ? `${delayMs}ms` : "0ms" }}
    >
      {children}
    </div>
  );
}
