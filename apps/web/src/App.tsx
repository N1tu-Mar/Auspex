import type { components } from "@auspex/contracts";
import { useEffect, useState } from "react";

type Health = components["schemas"]["HealthResponse"];
type State = { kind: "loading" } | { kind: "error" } | { kind: "ok"; health: Health };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? (r.json() as Promise<Health>) : Promise.reject(r.status)))
      .then((health) => setState({ kind: "ok", health }))
      .catch(() => setState({ kind: "error" }));
  }, []);

  return (
    <main>
      <h1>Auspex</h1>
      <p>Foundation status</p>
      <dl aria-live="polite">
        <dt>API</dt>
        <dd>{state.kind === "ok" ? state.health.status : state.kind}</dd>
        <dt>Database</dt>
        <dd>{state.kind === "ok" ? state.health.database : "unknown"}</dd>
      </dl>
    </main>
  );
}
