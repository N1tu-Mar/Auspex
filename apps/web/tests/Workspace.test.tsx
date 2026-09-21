import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";
import type { IntakeResult } from "../src/api";
import { Workspace } from "../src/Workspace";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

const resolved: IntakeResult = {
  trace_id: "0b6f7c1e-9a55-4c1b-8f8e-2f5a6d7e8c90",
  received_at_utc: "2026-09-21T14:02:11Z",
  source: "paste",
  state: "RESOLVED",
  original_input: "Chiefs ML @ 0.56",
  legs: [],
  issues: [],
  slip: {
    original_input: "Chiefs ML @ 0.56",
    stake_usd: "25",
    gross_payout_usd: "44.64",
    legs: [
      {
        sport: "NFL",
        league: "NFL",
        event_id: "evt-kc-buf",
        event_start_utc: "2026-09-27T20:25:00Z",
        home_participant: "Kansas City Chiefs",
        away_participant: "Buffalo Bills",
        market_type: "MONEYLINE",
        side: "HOME",
        market_price_usd: "0.56",
        settlement_rule_ref: "pm-us:nfl-ml-v1",
        status: "PREGAME",
      },
    ],
  },
};

const at = (iso: string) => new Date(iso);

test("workspace reports INSUFFICIENT_DATA and invents no metrics", () => {
  render(<Workspace intake={resolved} onBack={() => {}} now={at("2026-09-21T14:05:00Z")} />);

  const recommendation = screen.getByRole("region", { name: "Recommendation" });
  expect(within(recommendation).getByText("INSUFFICIENT_DATA")).toBeTruthy();
  expect(within(recommendation).getByText(/Analysis pipeline not yet connected/)).toBeTruthy();

  const comparison = screen.getByRole("region", { name: "Probability versus price" });
  const row = within(comparison).getAllByRole("row")[1] as HTMLElement;
  expect(within(row).getByText("0.56")).toBeTruthy();
  expect(within(row).getAllByText("Not estimated")).toHaveLength(2);

  for (const name of [
    "Legs, strongest to weakest",
    "Correlation warnings",
    "Freshness and missing data",
    "Explanation and sources",
    "Evidence and paper trade",
  ]) {
    expect(screen.getByRole("region", { name })).toBeTruthy();
  }
  expect(screen.getByText(/Not ranked/)).toBeTruthy();
  expect(screen.getByText("Not checked.")).toBeTruthy();
  expect(screen.getByText(/checked 2 min ago/)).toBeTruthy();
  expect(screen.queryByText(/Older than 15 minutes/)).toBeNull();
  // No percentages or computed probabilities anywhere.
  expect(document.body.textContent).not.toMatch(/\d+(\.\d+)?\s*%/);

  const paperTrade = screen.getByRole("button", { name: "Record paper trade" });
  expect(paperTrade.getAttribute("aria-disabled")).toBe("true");
  expect(
    document.getElementById(paperTrade.getAttribute("aria-describedby") ?? "")?.textContent,
  ).toMatch(/^Unavailable: a paper trade records the model estimate/);
  expect(screen.getByRole("button", { name: "Open evidence" })).toBeTruthy();
});

test("workspace flags old prices as stale", () => {
  render(<Workspace intake={resolved} onBack={() => {}} now={at("2026-09-21T14:40:00Z")} />);
  expect(screen.getByText(/checked 37 min ago/)).toBeTruthy();
  expect(screen.getByText(/Older than 15 minutes. Recheck prices/)).toBeTruthy();
});

test("workspace without a resolved slip points back to New analysis", async () => {
  const onBack = vi.fn();
  render(
    <Workspace intake={{ ...resolved, state: "NEEDS_RESOLUTION", slip: null }} onBack={onBack} />,
  );
  expect(screen.getByText(/No resolved slip in this tab/)).toBeTruthy();
  expect(screen.queryByText("INSUFFICIENT_DATA")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Go to New analysis" }));
  expect(onBack).toHaveBeenCalled();
});

test("navigation opens the workspace route and keeps the slip on return", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
  history.replaceState({ intake: resolved }, "", "/analysis");
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <App />
    </QueryClientProvider>,
  );
  const nav = screen.getByRole("navigation", { name: "Primary" });
  expect(
    within(nav).getByRole("link", { name: "Analysis workspace" }).getAttribute("aria-current"),
  ).toBe("page");
  expect(screen.getByText("INSUFFICIENT_DATA")).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Back to slip" }));
  expect(location.pathname).toBe("/");
  expect(screen.getByRole("heading", { name: "New analysis" })).toBeTruthy();
  expect(screen.queryByText("INSUFFICIENT_DATA")).toBeNull();

  await user.click(within(nav).getByRole("link", { name: "Analysis workspace" }));
  expect(location.pathname).toBe("/analysis");
  expect(screen.getByText("INSUFFICIENT_DATA")).toBeTruthy();
});
