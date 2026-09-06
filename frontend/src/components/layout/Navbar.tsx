import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

import { useScrolledPast } from "../../hooks/useScrolledPast";
import { CINEMATIC_SCROLL_HEIGHT_VH, CINEMATIC_TRANSITION_START } from "../../lib/cinematic";

// Every link below corresponds to a real, existing section or route — no
// placeholder destinations. Capabilities/Intelligence stay in-page hash
// anchors (they're landing-page storytelling sections); Route Planner,
// Ask ORCA, and Status are dedicated application pages, not anchors.
const HASH_LINKS = [
  { to: "/#capabilities", label: "Capabilities" },
  { to: "/#intelligence", label: "Intelligence" },
];

const PAGE_LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/fishing", label: "Fishing" },
  { to: "/safety", label: "Safety" },
  { to: "/marine-map", label: "Marine Map" },
  { to: "/route-planner", label: "Route Planner" },
  { to: "/ask-orca", label: "Ask ORCA" },
  { to: "/status", label: "Status" },
];

export function Navbar() {
  const { pathname } = useLocation();
  const isHome = pathname === "/";
  const [mobileOpen, setMobileOpen] = useState(false);

  // Match the cinematic hero's own hand-off point (see CinematicHero /
  // useCinematicScroll) rather than a fixed guess — the nav should only
  // turn solid once the frame sequence has started fading into the page.
  // Pages without a hero (e.g. /status) have no transparent phase.
  //
  // The hero's own progress is `scrollY / (heroHeightPx - viewportHeight)`
  // (see useCinematicScroll's `computeTarget`) — note the divisor is the
  // SCROLLABLE distance, not the raw section height. Using the raw height
  // here would put this threshold past the point where the hero actually
  // finishes and un-pins, leaving the nav transparent (with light,
  // over-cinematic text) while a page section is already visible behind it.
  const heroTransitionThresholdPx =
    typeof window === "undefined"
      ? 0
      : window.innerHeight * (CINEMATIC_SCROLL_HEIGHT_VH / 100 - 1) * CINEMATIC_TRANSITION_START;
  const scrolledPastHero = useScrolledPast(heroTransitionThresholdPx);
  const solid = !isHome || scrolledPastHero;

  // Nav text stays light (cream/white) in BOTH states — over the warm
  // cinematic hero, and over every below-hero/dedicated-page surface,
  // which are now deep-marine, not light cream. Only the header's own
  // background presence changes: fully transparent over the hero,
  // a translucent deep-marine glass surface everywhere else.
  const linkColorClass = "text-marine-white/75 hover:text-marine-white";
  const activeLinkColorClass = "text-marine-cyan-light";
  const logoColorClass = "text-marine-white";
  const iconColorClass = "text-marine-white";

  // Lock page scroll while the fullscreen mobile menu is open — a modal
  // overlay with the page scrolling behind it would be confusing — but
  // release it immediately on unmount/close so normal scrolling is never
  // permanently affected.
  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen]);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
        mobileOpen
          ? "bg-transparent"
          : solid
            ? "border-b border-marine-cyan/10 bg-marine-deep/85 backdrop-blur-md"
            : "bg-transparent"
      }`}
    >
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5" aria-label="Primary">
        <NavLink to="/" className={`text-lg font-semibold tracking-tight ${logoColorClass}`} aria-label="ORCA home">
          ORCA
        </NavLink>

        <ul className="hidden items-center gap-9 md:flex">
          {HASH_LINKS.map((link) => (
            <li key={link.to}>
              <a
                href={link.to}
                className={`text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan focus-visible:ring-offset-2 focus-visible:ring-offset-marine-deep rounded ${linkColorClass}`}
              >
                {link.label}
              </a>
            </li>
          ))}
          {PAGE_LINKS.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                className={({ isActive }) =>
                  `text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan focus-visible:ring-offset-2 focus-visible:ring-offset-marine-deep rounded ${
                    isActive ? activeLinkColorClass : linkColorClass
                  }`
                }
              >
                {link.label}
              </NavLink>
            </li>
          ))}
        </ul>

        <NavLink
          to="/ask-orca"
          className="hidden rounded-full bg-marine-cyan px-4 py-2 text-sm font-semibold text-marine-deep transition-colors hover:bg-marine-cyan-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan-light md:inline-block"
        >
          Open ORCA
        </NavLink>

        <button
          type="button"
          className={`relative z-[60] inline-flex h-9 w-9 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan md:hidden ${iconColorClass}`}
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav-menu"
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          onClick={() => setMobileOpen((open) => !open)}
        >
          <Menu
            className={`absolute h-6 w-6 transition-all duration-300 ${mobileOpen ? "rotate-90 opacity-0" : "rotate-0 opacity-100"}`}
            strokeWidth={1.75}
          />
          <X
            className={`absolute h-6 w-6 transition-all duration-300 ${mobileOpen ? "rotate-0 opacity-100" : "-rotate-90 opacity-0"}`}
            strokeWidth={1.75}
          />
        </button>
      </nav>

      {/* Fullscreen mobile menu — a deep-marine takeover. */}
      <div
        id="mobile-nav-menu"
        className={`fixed inset-0 top-0 z-50 flex flex-col bg-marine-deep backdrop-blur-md transition-opacity duration-300 md:hidden ${
          mobileOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        aria-hidden={!mobileOpen}
      >
        <div className="flex items-center justify-between px-6 py-5">
          <span className="text-lg font-semibold tracking-tight text-marine-white">ORCA</span>
          <div className="h-9 w-9" aria-hidden="true" />
        </div>
        <ul className="flex flex-1 flex-col items-start justify-center gap-6 px-8">
          <li>
            <NavLink
              to="/"
              onClick={() => setMobileOpen(false)}
              tabIndex={mobileOpen ? 0 : -1}
              className="text-3xl font-semibold tracking-tight text-marine-white"
            >
              Home
            </NavLink>
          </li>
          {HASH_LINKS.map((link) => (
            <li key={link.to}>
              <a
                href={link.to}
                onClick={() => setMobileOpen(false)}
                tabIndex={mobileOpen ? 0 : -1}
                className="text-3xl font-semibold tracking-tight text-marine-white/80 hover:text-marine-cyan-light"
              >
                {link.label}
              </a>
            </li>
          ))}
          {PAGE_LINKS.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                onClick={() => setMobileOpen(false)}
                tabIndex={mobileOpen ? 0 : -1}
                className={({ isActive }) =>
                  `text-3xl font-semibold tracking-tight ${isActive ? "text-marine-cyan-light" : "text-marine-white/80 hover:text-marine-cyan-light"}`
                }
              >
                {link.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="px-8 pb-10">
          <NavLink
            to="/ask-orca"
            onClick={() => setMobileOpen(false)}
            tabIndex={mobileOpen ? 0 : -1}
            className="block rounded-full bg-marine-cyan px-5 py-3 text-center text-sm font-semibold text-marine-deep hover:bg-marine-cyan-light"
          >
            Open ORCA
          </NavLink>
        </div>
      </div>
    </header>
  );
}
