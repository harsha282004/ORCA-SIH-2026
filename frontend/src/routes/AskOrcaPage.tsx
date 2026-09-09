import { AskOrca } from "../components/app/AskOrca";

/**
 * The dedicated Ask ORCA workspace — the existing `AskOrca` component
 * (unchanged logic, still calling the real `POST /api/v1/query`) inside a
 * focused, deep-marine page shell.
 */
export function AskOrcaPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-marine-deep pt-20">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(56,189,248,0.12),_transparent_60%)]"
        aria-hidden="true"
      />
      <div className="relative mx-auto max-w-3xl px-6 py-16 sm:px-10 sm:py-20">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Live &amp; Interactive</p>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-marine-white sm:text-5xl">Ask ORCA.</h1>
        <p className="mt-4 text-base text-marine-white/70">Ask ORCA about marine conditions, safety, fishing, or routes.</p>

        <div className="mt-8">
          <AskOrca />
        </div>
      </div>
    </main>
  );
}
