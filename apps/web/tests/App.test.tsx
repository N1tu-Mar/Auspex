import type { components } from "@auspex/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";

const renderApp = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <App />
    </QueryClientProvider>,
  );

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows API and database health", async () => {
  const health: components["schemas"]["HealthResponse"] = { status: "ok", database: "ok" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(health))));
  renderApp();
  expect(await screen.findAllByText("ok")).toHaveLength(2);
});

test("shows error when API is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  renderApp();
  expect(await screen.findByText("error")).toBeTruthy();
});
