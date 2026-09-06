import { RevealOnScroll } from "../common/RevealOnScroll";

// The real orchestration graph — backend/app/orchestration/graph.py.
// Deliberately marks which stages are LLM-driven vs. deterministic code,
// since that separation is ORCA's core architectural principle. No RAG,
// no vector store, no LangChain, no Ollama — this is the actual pipeline.
const PIPELINE = [
  { label: "You ask a question", detail: "“Is it safe to go fishing near Mangaluru tomorrow morning?”", kind: "input" as const },
  { label: "Query Understanding", detail: "An LLM extracts location, time, and intent — never inventing coordinates or dates itself.", kind: "ai" as const },
  { label: "LangGraph Orchestration", detail: "Dispatches the Weather, Oceanographic, and GIS agents in parallel.", kind: "system" as const },
  { label: "Risk & Suitability Engine", detail: "Deterministic, weighted scoring of wave, wind, hazard, and geofence-distance signals.", kind: "deterministic" as const },
  { label: "Safety Guard", detail: "A fail-closed check — missing, stale, or low-confidence data can only ever block, never be waved through.", kind: "deterministic" as const },
  { label: "Decision Engine", detail: "Produces one of four structured outcomes — the LLM never chooses this.", kind: "deterministic" as const },
  { label: "Evidence & Explanation", detail: "An LLM writes the explanation, grounded only in the computed evidence — it cannot contradict the decision.", kind: "ai" as const },
  { label: "You receive a grounded answer", detail: "A recommendation you can trace back to real evidence.", kind: "output" as const },
];

const KIND_STYLES: Record<string, string> = {
  input: "border-marine-white/25 text-marine-white/80",
  ai: "border-marine-cyan-light/60 text-marine-cyan-light",
  system: "border-marine-white/25 text-marine-white/80",
  deterministic: "border-marine-white text-marine-white",
  output: "border-marine-white/25 text-marine-white/80",
};

const KIND_TAG: Record<string, string> = {
  input: "You",
  ai: "LLM",
  system: "Orchestration",
  deterministic: "Deterministic",
  output: "Response",
};

export function AIIntelligenceSection() {
  return (
    <section id="intelligence" className="scroll-mt-20 bg-marine-ocean px-6 py-28 sm:px-10 sm:py-36 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll className="max-w-2xl">
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">How ORCA Thinks</p>
          <h2 className="mt-4 text-3xl font-semibold tracking-tight text-marine-white sm:text-5xl">
            Intelligence, with a deterministic safety net.
          </h2>
          <p className="mt-5 max-w-xl text-sm leading-relaxed text-marine-white/70 sm:text-base">
            The LLM interprets and explains. It never computes risk, never enforces safety, and never overrides
            the decision engine.
          </p>
        </RevealOnScroll>

        <ol className="relative mt-16 border-l border-marine-white/15 pl-8 sm:pl-12">
          {PIPELINE.map((step, index) => (
            <RevealOnScroll key={step.label} delayMs={index * 70} className="relative">
              <li className={index === PIPELINE.length - 1 ? "pb-0" : "pb-12"}>
                <span
                  className={`absolute -left-[calc(2rem+1px)] top-1 flex h-4 w-4 -translate-x-1/2 items-center justify-center rounded-full border bg-marine-ocean sm:-left-[calc(3rem+1px)] ${KIND_STYLES[step.kind]}`}
                  aria-hidden="true"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                </span>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-marine-white/40">{String(index + 1).padStart(2, "0")}</span>
                  <p className="text-lg font-semibold text-marine-white sm:text-xl">{step.label}</p>
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${KIND_STYLES[step.kind]}`}>
                    {KIND_TAG[step.kind]}
                  </span>
                </div>
                <p className="mt-2 max-w-xl text-sm leading-relaxed text-marine-white/70 sm:text-base">{step.detail}</p>
              </li>
            </RevealOnScroll>
          ))}
        </ol>
      </div>
    </section>
  );
}
