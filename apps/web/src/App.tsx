import type { components } from "@auspex/contracts";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { IntakeResult } from "./api";
import { NewAnalysis } from "./NewAnalysis";
import { navigate, type Path, useLocation } from "./router";
import { Workspace } from "./Workspace";

type Health = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<Health> {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function App() {
  const { path, state } = useLocation();
  const intake = (state as { intake?: IntakeResult } | null)?.intake;
  // Last slip opened in the workspace, so the nav link can return to it.
  const [lastIntake, setLastIntake] = useState(intake);
  const openWorkspace = (result: IntakeResult | undefined) => {
    if (result) setLastIntake(result);
    navigate("/analysis", result ? { intake: result } : null);
  };

  const viewStart = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);
  // After a route change, move focus to the new view so keyboard and screen-reader users land
  // on its content. The first render keeps the browser's default focus.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs on route change only.
  useEffect(() => {
    if (firstRender.current) firstRender.current = false;
    else viewStart.current?.focus();
  }, [path]);
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });
  const status = health.data?.status ?? (health.isError ? "error" : "loading");
  const database = health.data?.database ?? "unknown";
  const tone = (value: string) =>
    value === "ok" ? "text-ok" : health.isPending ? "text-muted" : "text-bad";

  return (
    <div className="min-h-screen bg-ground font-sans text-ink">
      <header className="border-b border-rule bg-panel">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <h1 className="font-mono text-base font-semibold uppercase tracking-[0.2em]">Auspex</h1>
          <p className="text-xs text-muted">Pregame research · paper trading only</p>
          <nav aria-label="Primary" className="flex gap-1 text-sm">
            <NavLink current={path === "/"} onClick={() => navigate("/")} href="/">
              New analysis
            </NavLink>
            <NavLink
              current={path === "/analysis"}
              onClick={() => openWorkspace(intake ?? lastIntake)}
              href="/analysis"
            >
              Analysis workspace
            </NavLink>
          </nav>
          <dl aria-live="polite" className="ml-auto flex gap-4 font-mono text-xs">
            <div className="flex gap-1.5">
              <dt className="text-muted">API</dt>
              <dd className={tone(status)}>{status}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted">Database</dt>
              <dd className={tone(database)}>{database}</dd>
            </div>
          </dl>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div ref={viewStart} tabIndex={-1} aria-hidden="true" className="outline-none" />
        {/* Kept mounted while hidden so the slip being edited survives a trip to the workspace. */}
        <div hidden={path !== "/"}>
          <h2 className="mb-1 text-xl font-semibold">New analysis</h2>
          <p className="mb-6 max-w-2xl text-sm text-muted">
            Enter a position, resolve every leg to a specific pregame market, then review the slip.
            Nothing is guessed: unclear legs stay open until you settle them.
          </p>
          <NewAnalysis onContinue={openWorkspace} />
        </div>
        {path === "/analysis" && <Workspace intake={intake} onBack={() => navigate("/")} />}
      </main>
    </div>
  );
}

function NavLink({
  href,
  current,
  onClick,
  children,
}: {
  href: Path;
  current: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      aria-current={current ? "page" : undefined}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        onClick();
      }}
      className="rounded-sm px-2 py-1 text-muted hover:bg-rule/40 aria-[current=page]:bg-rule/50 aria-[current=page]:text-ink"
    >
      {children}
    </a>
  );
}
