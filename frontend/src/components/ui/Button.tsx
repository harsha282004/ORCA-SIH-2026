import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { Loader2 } from "lucide-react";

/**
 * Phase 11 — the ORCA design system's one shared button primitive. Every
 * page previously improvised its own inline button classes (or, worse,
 * used a plain underlined text link for a primary action — task §"Convert
 * 'View Route Planner →' into a proper button"). `Button` renders a native
 * `<button>`; `ButtonLink` renders a react-router `<Link>` with the exact
 * same visual treatment, so a navigational CTA and an action CTA are
 * visually indistinguishable in intent, only in what they do.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

// Theme correction: every real call site for this component lives on a
// LIGHT app-page surface now (Dashboard/Fishing/Safety/Route Planner/Ask
// ORCA all moved off marine-deep — see each page's own redesign notes).
// "secondary"/"ghost" used to be light-cyan-on-transparent, calibrated for
// a dark glass surface — on white that's ~1.5:1 contrast, functionally
// invisible. Both are now genuinely readable on white/off-white.
const BASE =
  "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-blue focus-visible:ring-offset-2 focus-visible:ring-offset-marine-surface disabled:cursor-not-allowed disabled:opacity-50";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-marine-cyan text-marine-deep hover:bg-marine-cyan-light",
  secondary: "border border-marine-blue/30 bg-marine-mist text-marine-blue hover:border-marine-blue hover:bg-marine-frost",
  ghost: "border border-marine-border text-marine-ink hover:border-marine-blue/40 hover:bg-marine-surface-alt",
  danger: "border border-marine-danger/40 text-marine-danger hover:bg-marine-danger/10",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "px-3.5 py-1.5 text-xs",
  md: "px-5 py-2.5 text-sm",
  lg: "px-7 py-3.5 text-base",
};

function classes(variant: ButtonVariant, size: ButtonSize, className?: string) {
  return `${BASE} ${VARIANT[variant]} ${SIZE[size]} ${className ?? ""}`;
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button ref={ref} type={rest.type ?? "button"} disabled={disabled || loading} className={classes(variant, size, className)} {...rest}>
      {loading && <Loader2 size={size === "lg" ? 18 : 14} className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  );
});

interface ButtonLinkProps extends LinkProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function ButtonLink({ variant = "primary", size = "md", className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={classes(variant, size, className)} {...rest}>
      {children}
    </Link>
  );
}
