import type { components } from "@auspex/contracts";
import { useQuery } from "@tanstack/react-query";
import { NewAnalysis } from "./NewAnalysis";

type Health = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<Health> {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });
  const status = health.data?.status ?? (health.isError ? "error" : "loading");
  const database = health.data?.database ?? "unknown";

  return (
    <div className="min-h-screen bg-ground font-sans text-ink">
      <header className="border-b border-rule bg-panel">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <h1 className="font-mono text-base font-semibold uppercase tracking-[0.2em]">Auspex</h1>
          <p className="text-xs text-muted">Pregame research · paper trading only</p>
          <dl aria-live="polite" className="ml-auto flex gap-4 font-mono text-xs">
            <div className="flex gap-1.5">
              <dt className="text-muted">API</dt>
              <dd className={status === "ok" ? "text-ok" : "text-bad"}>{status}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted">Database</dt>
              <dd className={database === "ok" ? "text-ok" : "text-bad"}>{database}</dd>
            </div>
          </dl>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <h2 className="mb-1 text-xl font-semibold">New analysis</h2>
        <p className="mb-6 max-w-2xl text-sm text-muted">
          Enter a position, resolve every leg to a specific pregame market, then review the slip.
          Nothing is guessed: unclear legs stay open until you settle them.
        </p>
        <NewAnalysis />
      </main>
    </div>
  );
}
