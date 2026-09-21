import type { components } from "@auspex/contracts";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows API and database health", async () => {
  const health: components["schemas"]["HealthResponse"] = { status: "ok", database: "ok" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(health))));
  render(<App />);
  expect(await screen.findAllByText("ok")).toHaveLength(2);
});

test("shows error when API is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<App />);
  expect(await screen.findByText("error")).toBeTruthy();
});
