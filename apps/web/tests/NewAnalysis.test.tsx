import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { BetSlip, IntakeError, IntakeResult } from "../src/api";
import { NewAnalysis } from "../src/NewAnalysis";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup(...replies: (Response | Error | "hang")[]) {
  const fetch = vi.fn();
  for (const reply of replies) {
    if (reply === "hang") fetch.mockReturnValueOnce(new Promise(() => {}));
    else if (reply instanceof Error) fetch.mockRejectedValueOnce(reply);
    else fetch.mockResolvedValueOnce(reply);
  }
  vi.stubGlobal("fetch", fetch);
  const onContinue = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NewAnalysis onContinue={onContinue} />
    </QueryClientProvider>,
  );
  const body = (call: number) => JSON.parse(fetch.mock.calls[call]?.[1].body);
  return { fetch, body, onContinue, user: userEvent.setup() };
}

const base = {
  trace_id: "0b6f7c1e-9a55-4c1b-8f8e-2f5a6d7e8c90",
  received_at_utc: "2026-09-21T14:02:11Z",
  original_input: "Chiefs ML @ 0.56",
};

const notFound: IntakeResult = {
  ...base,
  source: "paste",
  state: "NEEDS_RESOLUTION",
  legs: [
    {
      index: 0,
      state: "NEEDS_RESOLUTION",
      raw_text: "Chiefs ML @ 0.56",
      market_type: "MONEYLINE",
      market_price_usd: "0.56",
    },
  ],
  issues: [{ code: "EVENT_NOT_FOUND", message: "No known event matches Chiefs.", leg_index: 0 }],
  slip: null,
};

const candidate = {
  sport: "NFL",
  league: "NFL",
  event_start_utc: "2026-09-27T20:25:00Z",
  home_participant: "Kansas City Chiefs",
  away_participant: "Buffalo Bills",
} as const;

async function pasteSlip(user: ReturnType<typeof userEvent.setup>, text = "Chiefs ML @ 0.56") {
  await user.type(screen.getByLabelText("Slip text"), text);
  await user.type(screen.getByLabelText("Stake (USD)"), "25");
  await user.click(screen.getByRole("button", { name: "Parse into legs" }));
}

test("starts empty with direction instead of a blank screen", () => {
  setup();
  expect(screen.getByText(/Nothing checked yet/)).toBeTruthy();
  expect(screen.getByText(/No legs yet/)).toBeTruthy();
});

test("pasted text becomes an editable leg, then a resolved slip for review", async () => {
  const slip: BetSlip = {
    original_input: "Chiefs ML @ 0.56",
    stake_usd: "25",
    gross_payout_usd: null,
    legs: [
      {
        ...candidate,
        event_id: "evt-kc-buf",
        market_type: "MONEYLINE",
        side: "HOME",
        market_price_usd: "0.56",
        settlement_rule_ref: "pm-us:nfl-ml-v1",
        status: "PREGAME",
      },
    ],
  };
  const resolved: IntakeResult = {
    ...base,
    source: "manual",
    state: "RESOLVED",
    legs: [{ index: 0, state: "RESOLVED", ...slip.legs[0] }],
    issues: [],
    slip,
  };
  const { user, body, onContinue } = setup(json(notFound), json(resolved));

  await pasteSlip(user);
  expect(body(0)).toEqual({ text: "Chiefs ML @ 0.56", stake_usd: "25", gross_payout_usd: null });
  expect(await screen.findByText("No known event matches Chiefs.")).toBeTruthy();
  const check = screen.getByRole("complementary", { name: "Intake check" });
  expect(within(check).getByText("Needs resolution")).toBeTruthy();
  expect(within(check).getByText("From pasted text")).toBeTruthy();
  expect(within(check).getByText(/No live event catalog is connected yet/)).toBeTruthy();
  expect(screen.getByText("Pasted: Chiefs ML @ 0.56")).toBeTruthy();
  expect((screen.getByLabelText("Market type") as HTMLSelectElement).value).toBe("MONEYLINE");
  expect((screen.getByLabelText("Price (USD)") as HTMLInputElement).value).toBe("0.56");
  expect((screen.getByLabelText("Side") as HTMLSelectElement).value).toBe("");

  await user.selectOptions(screen.getByLabelText("Sport"), "NFL");
  await user.type(screen.getByLabelText("League"), "NFL");
  fireEvent.change(screen.getByLabelText("Event start (local time)"), {
    target: { value: "2026-09-27T20:25" },
  });
  await user.type(screen.getByLabelText("Home"), "Kansas City Chiefs");
  await user.type(screen.getByLabelText("Away"), "Buffalo Bills");
  await user.type(screen.getByLabelText("Event ID"), "evt-kc-buf");
  await user.selectOptions(screen.getByLabelText("Side"), "HOME");
  await user.type(screen.getByLabelText("Settlement rule reference"), "pm-us:nfl-ml-v1");
  expect(screen.getByRole("alert").textContent).toMatch(/Out of date/);

  await user.click(screen.getByRole("button", { name: "Check legs" }));

  const sent = body(1) as BetSlip;
  expect(sent.stake_usd).toBe("25");
  expect(sent.original_input).toBe("Chiefs ML @ 0.56");
  expect(sent.legs[0]).toMatchObject({
    sport: "NFL",
    event_id: "evt-kc-buf",
    side: "HOME",
    line: null,
    market_price_usd: "0.56",
    status: "PREGAME",
    event_start_utc: new Date("2026-09-27T20:25").toISOString(),
  });

  const review = await screen.findByRole("region", { name: "Resolved slip" });
  const row = within(review).getAllByRole("row")[1] as HTMLElement;
  expect(within(row).getByText("Buffalo Bills at Kansas City Chiefs")).toBeTruthy();
  expect(within(row).getByText("NFL · 2026-09-27 20:25 UTC")).toBeTruthy();
  expect(within(row).getByText("0.56")).toBeTruthy();
  expect(within(row).getByText("Moneyline · Home")).toBeTruthy();
  expect(within(row).getByText("pm-us:nfl-ml-v1")).toBeTruthy();
  expect(within(row).getByText("Pregame ·", { exact: false })).toBeTruthy();
  expect(within(review).getByRole("rowheader", { name: "Stake (USD)" })).toBeTruthy();
  expect(within(review).getByText("Not quoted")).toBeTruthy();
  expect(screen.getByText(/Checked 2026-09-21 14:02:11 UTC · manual/)).toBeTruthy();
  expect(within(review).getByText(/reports\s+INSUFFICIENT_DATA/)).toBeTruthy();
  await user.click(within(review).getByRole("button", { name: "Open analysis workspace" }));
  expect(onContinue).toHaveBeenCalledWith(resolved);
  expect(screen.queryByText(/probability of/i)).toBeNull();

  await user.clear(screen.getByLabelText("Price (USD)"));
  await user.type(screen.getByLabelText("Price (USD)"), "0.6");
  expect(screen.getByRole("alert").textContent).toMatch(/Out of date/);
  expect(screen.queryByRole("region", { name: "Resolved slip" })).toBeNull();
});

test("ambiguous events are listed for the user to choose, never auto-picked", async () => {
  const ambiguous: IntakeResult = {
    ...notFound,
    legs: [
      {
        ...notFound.legs[0],
        index: 0,
        state: "NEEDS_RESOLUTION",
        candidates: [
          { ...candidate, event_id: "evt-1" },
          { ...candidate, event_id: "evt-2", event_start_utc: "2027-01-10T18:00:00Z" },
        ],
      },
    ],
    issues: [
      {
        code: "AMBIGUOUS_EVENT",
        message: "2 events match; choose one.",
        leg_index: 0,
        field: "event_id",
      },
    ],
  };
  const { user } = setup(json(ambiguous));
  await pasteSlip(user);

  const group = await screen.findByRole("group", { name: /2 events match/ });
  expect((screen.getByLabelText("Event ID") as HTMLInputElement).value).toBe("");
  expect(screen.getByText("2 events match; choose one. (AMBIGUOUS_EVENT)")).toBeTruthy();

  await user.click(within(group).getAllByRole("radio")[1] as HTMLElement);
  expect((screen.getByLabelText("Event ID") as HTMLInputElement).value).toBe("evt-2");
  expect((screen.getByLabelText("Home") as HTMLInputElement).value).toBe("Kansas City Chiefs");
  expect((screen.getByLabelText("Sport") as HTMLSelectElement).value).toBe("NFL");
});

test("live markets are rejected and labelled unsupported", async () => {
  const rejected: IntakeResult = {
    ...notFound,
    state: "REJECTED",
    legs: [{ ...notFound.legs[0], index: 0, state: "REJECTED", status: "LIVE" }],
    issues: [
      {
        code: "UNSUPPORTED_STATUS",
        message: "LIVE legs are not supported.",
        leg_index: 0,
        field: "status",
      },
    ],
  };
  const { user } = setup(json(rejected));
  await pasteSlip(user);

  expect(await screen.findByText(/Only pregame markets are supported/)).toBeTruthy();
  const check = screen.getByRole("complementary", { name: "Intake check" });
  expect(within(check).getByText("How to fix")).toBeTruthy();
  expect(within(check).getByText(/set status to Pregame; otherwise remove the leg/)).toBeTruthy();
  expect(screen.getAllByText("Rejected").length).toBeGreaterThan(0);
  const status = screen.getByLabelText("Market status");
  expect(status.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(status.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
    "LIVE legs are not supported. (UNSUPPORTED_STATUS)",
  );
});

test("provider failure is explicit, keeps input, and can be retried", async () => {
  const { user, fetch } = setup(new TypeError("offline"), json(notFound));
  await pasteSlip(user);

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/Intake service unavailable/);
  expect(alert.textContent).toMatch(/Could not reach the intake service/);
  expect((screen.getByLabelText("Slip text") as HTMLTextAreaElement).value).toBe(
    "Chiefs ML @ 0.56",
  );

  await user.click(within(alert).getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No known event matches Chiefs.")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.queryByText(/Intake service unavailable/)).toBeNull();
});

test("a server error without a result is reported as unavailable", async () => {
  const { user } = setup(new Response("upstream timeout", { status: 503 }));
  await pasteSlip(user);
  expect((await screen.findByRole("alert")).textContent).toMatch(/HTTP 503 without a result/);
});

test("malformed input reported by the API lists each field", async () => {
  const error: IntakeError = {
    trace_id: base.trace_id,
    received_at_utc: base.received_at_utc,
    code: "MALFORMED_INPUT",
    message: "Request body is malformed.",
    issues: [
      {
        code: "MALFORMED_INPUT",
        message: "Input should be greater than 0",
        field: "stake_usd",
      },
    ],
  };
  const { user } = setup(json(error, 422));
  await pasteSlip(user);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/could not read this slip/);
  expect(alert.textContent).toMatch(/stake_usd Input should be greater than 0/);
  expect(within(alert).queryByRole("button", { name: "Try again" })).toBeNull();
});

test("invalid input is caught before any request", async () => {
  const { user, fetch } = setup();
  await user.click(screen.getByRole("button", { name: "Parse into legs" }));
  expect(screen.getByText(/Paste at least one leg/)).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Add leg" }));
  await user.type(screen.getByLabelText("Price (USD)"), "1.2");
  await user.click(screen.getByRole("button", { name: "Check legs" }));

  expect(await screen.findByText(/Price must be above 0 and below 1 USD/)).toBeTruthy();
  expect(screen.getByText(/Stake must be a positive USD amount/)).toBeTruthy();
  expect(screen.getByText("Choose a sport.")).toBeTruthy();
  expect(screen.getByLabelText("Price (USD)").getAttribute("aria-invalid")).toBe("true");
  expect(fetch).not.toHaveBeenCalled();
});

test("shows loading while the intake service works", async () => {
  const { user, fetch } = setup("hang");
  await pasteSlip(user);
  expect(await screen.findByText("Checking with the intake service…")).toBeTruthy();
  // aria-disabled, not disabled, so keyboard focus stays on the button while pending.
  const parse = screen.getByRole("button", { name: "Parsing…" });
  expect(parse.getAttribute("aria-disabled")).toBe("true");
  expect(screen.getByRole("button", { name: "Check legs" }).getAttribute("aria-disabled")).toBe(
    "true",
  );
  await user.click(parse);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("legs can be added and removed by hand", async () => {
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "Add leg" }));
  await user.click(screen.getByRole("button", { name: "Add leg" }));
  expect(screen.getAllByRole("group", { name: /^Leg \d$/ })).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Remove leg 1" }));
  expect(screen.getAllByRole("group", { name: /^Leg \d$/ })).toHaveLength(1);
});

test("a partly resolved combo says which legs are ready without guessing the rest", async () => {
  const partial: IntakeResult = {
    ...notFound,
    original_input: "Chiefs ML @ 0.56; Chiefs to win big",
    legs: [
      {
        index: 0,
        state: "RESOLVED",
        raw_text: "Chiefs ML @ 0.56",
        ...candidate,
        event_id: "evt-kc-buf",
        market_type: "MONEYLINE",
        side: "HOME",
        market_price_usd: "0.56",
        settlement_rule_ref: "pm-us:nfl-ml-v1",
        status: "PREGAME",
      },
      { index: 1, state: "NEEDS_RESOLUTION", raw_text: "Chiefs to win big" },
    ],
    issues: [
      {
        code: "UNPARSEABLE_LEG",
        message: "Use 'Team ML', 'Team -3.5', or 'Team A/Team B over 47.5', each with '@ price'.",
        leg_index: 1,
      },
    ],
  };
  const { user } = setup(json(partial));
  await pasteSlip(user, "Chiefs ML @ 0.56; Chiefs to win big");

  expect(await screen.findByText(/Partly resolved: 1 of 2 legs are ready/)).toBeTruthy();
  const review = screen.getByRole("region", { name: "Intake legs" });
  const rows = within(review).getAllByRole("row");
  expect(within(rows[1] as HTMLElement).getByText("Resolved")).toBeTruthy();
  expect(within(rows[2] as HTMLElement).getByText("Chiefs to win big")).toBeTruthy();
  expect(within(rows[2] as HTMLElement).getByText("Market not set · side not set")).toBeTruthy();
  expect(within(rows[2] as HTMLElement).getByText("Unconfirmed")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Resolved slip" })).toBeNull();
});
