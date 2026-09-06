import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="border-t border-marine-cyan/10 bg-marine-deep px-6 py-12 sm:px-10 lg:px-16">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-sm">
          <p className="text-lg font-semibold tracking-tight text-marine-white">ORCA</p>
          <p className="mt-2 text-sm leading-relaxed text-marine-white/70">
            Marine EcOsystem Reasoning with Collaborative Agents — AI-driven coastal and fishing intelligence for
            the Mangaluru–Udupi coast.
          </p>
        </div>

        <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
          <a href="/#capabilities" className="text-marine-white/70 hover:text-marine-cyan-light">
            Capabilities
          </a>
          <a href="/#intelligence" className="text-marine-white/70 hover:text-marine-cyan-light">
            Intelligence
          </a>
          <Link to="/route-planner" className="text-marine-white/70 hover:text-marine-cyan-light">
            Route Planner
          </Link>
          <Link to="/ask-orca" className="text-marine-white/70 hover:text-marine-cyan-light">
            Ask ORCA
          </Link>
          <Link to="/status" className="text-marine-white/70 hover:text-marine-cyan-light">
            Status
          </Link>
        </nav>
      </div>

      <div className="mx-auto mt-10 flex max-w-7xl flex-col gap-2 border-t border-marine-cyan/10 pt-6 text-xs text-marine-white/50 sm:flex-row sm:items-center sm:justify-between">
        <span>Smart India Hackathon — SIH26176 · Disaster Management</span>
        <span>An engineering prototype — not an official maritime advisory.</span>
      </div>
    </footer>
  );
}
