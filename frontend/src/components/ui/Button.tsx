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

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan-light focus-visible:ring-offset-2 focus-visible:ring-offset-marine-deep disabled:cursor-not-allowed disabled:opacity-50";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-marine-cyan text-marine-deep hover:bg-marine-cyan-light",
  secondary: "border border-marine-cyan/30 bg-marine-cyan/10 text-marine-cyan-light hover:border-marine-cyan hover:bg-marine-cyan/20",
  ghost: "border border-marine-white/15 text-marine-white/80 hover:border-marine-white/40 hover:bg-marine-white/5",
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
