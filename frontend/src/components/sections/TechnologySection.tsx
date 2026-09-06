import { RevealOnScroll } from "../common/RevealOnScroll";

// Only technologies actually present in the repository's dependency
// manifests (frontend/package.json, backend/requirements.txt).
const STACK = ["React", "TypeScript", "Vite", "Tailwind CSS", "MapLibre GL", "FastAPI", "SQLAlchemy", "PostgreSQL / PostGIS", "Redis", "LangGraph"];

export function TechnologySection() {
  return (
    <section className="bg-marine-ocean px-6 py-24 sm:px-10 sm:py-32 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <RevealOnScroll>
          <p className="text-xs font-medium uppercase tracking-[0.3em] text-marine-cyan-light">Under the Hood</p>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight text-marine-white sm:text-4xl">
            Built on a real, tested stack.
          </h2>
        </RevealOnScroll>

        <RevealOnScroll delayMs={100}>
          <ul className="mt-10 flex flex-wrap gap-3">
            {STACK.map((tech) => (
              <li key={tech} className="rounded-full border border-marine-cyan/25 bg-marine-cyan/5 px-4 py-1.5 text-sm text-marine-white">
                {tech}
              </li>
            ))}
          </ul>
        </RevealOnScroll>
      </div>
    </section>
  );
}
