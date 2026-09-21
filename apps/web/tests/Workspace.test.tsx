import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";
import type { AnalysisRecord } from "../src/api";
import { fixed, pct, signed, usd } from "../src/decimal";
import { Workspace } from "../src/Workspace";
import { ANALYSIS_ID, AS_OF, item, noData, resolved, SLIP_ID, success } from "./fixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const at = (iso: string) => new Date(iso);
const region = (name: string) => screen.getByRole("region", { name });

function mount(props: Partial<Parameters<typeof Workspace>[0]> = {}) {
  const onOpen = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Workspace
        intake={resolved}
        onBack={() => {}}
        onOpen={onOpen}
        now={at("2026-09-21T14:07:00Z")}
        {...props}
      />
    </QueryClientProvider>,
  );
  return onOpen;
}

const stubFetch = (...responses: (Response | Error)[]) => {
  const fetch = vi.fn();
  for (const r of responses)
    r instanceof Error ? fetch.mockRejectedValueOnce(r) : fetch.mockResolvedValueOnce(r);
  vi.stubGlobal("fetch", fetch);
  return fetch;
};

const withRecord = (record: AnalysisRecord, patch: Partial<AnalysisRecord>) => ({
  ...record,
  ...patch,
});

test("decimal formatting is exact and never goes through floats", () => {
  expect(pct("0.5432")).toBe("54.3%");
  expect(pct("0.0005")).toBe("0.1%");
  expect(fixed("0.1234567890123456789", 4)).toBe("0.1235");
  expect(usd("1.8400")).toBe("$1.84");
  expect(usd("-0.005")).toBe("-$0.01");
  expect(signed("5.25", " pts")).toBe("+5.3 pts");
  expect(signed("-0.04", "%")).toBe("0.0%");
  expect(pct("1e-7")).toBe("1e-7%"); // unparseable is shown, not guessed
});

test("runs analysis from a resolved slip and shows every panel", async () => {
  const fetch = stubFetch(json(success, 201));
  const onOpen = mount();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/Estimated fees/), "0.50");
  await user.click(screen.getByRole("button", { name: "Run analysis" }));

  expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body)).toEqual({
    bet_slip_id: SLIP_ID,
    estimated_fees_usd: "0.50",
  });
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith(ANALYSIS_ID));
  const recommendation = region("Recommendation");
  expect(within(recommendation).getByText("CONSIDER")).toBeTruthy();

  const row = within(region("Probability versus price")).getAllByRole("row")[1] as HTMLElement;
  expect(row.textContent).toContain("Kansas City Chiefs"); // leg named from the matching slip
  expect(row.textContent).toContain("56.0%");
  expect(row.textContent).toContain("54.3%");
  expect(row.textContent).toContain("61.3% (55.0%–67.0%)");
  expect(row.textContent).toContain("+5.3 pts");

  const ev = region("Expected value");
  expect(ev.textContent).toContain("57.1%");
  expect(ev.textContent).toContain("$1.84");
  expect(ev.textContent).toContain("+7.4%");
  expect(within(region("Combo and correlation")).getByText(/Single leg/)).toBeTruthy();
  expect(screen.queryByText(/Partial result/)).toBeNull();
  expect(screen.queryByText(/Stale:/)).toBeNull();
  expect(screen.queryByText(/Conflicting evidence/)).toBeNull();
});

test("run form guards money input, pending state, and retries after failure", async () => {
  let release: (r: Response) => void = () => {};
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  fetch.mockImplementationOnce(() => Promise.reject(new TypeError("offline")));
  fetch.mockImplementationOnce(
    () =>
      new Promise<Response>((r) => {
        release = r;
      }),
  );
  mount();
  const user = userEvent.setup();

  await user.type(screen.getByLabelText(/Estimated fees/), "0.505");
  expect(screen.getByText(/dollars and cents/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
  expect(fetch).not.toHaveBeenCalled();

  await user.clear(screen.getByLabelText(/Estimated fees/));
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
  expect((await screen.findByRole("alert")).textContent).toMatch(
    /Could not reach the analysis service/,
  );

  const retry = screen.getByRole("button", { name: "Retry" });
  await user.click(retry);
  await user.click(retry); // double submit while pending is ignored
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: /Analysing/ }).getAttribute("aria-disabled")).toBe(
    "true",
  );
  release(json(success, 201));
  await waitFor(() => expect(screen.queryByRole("button", { name: /Analysing/ })).toBeNull());
  expect(screen.getByText("CONSIDER")).toBeTruthy();
});

test("refused analysis shows the server message", async () => {
  stubFetch(json({ code: "INTAKE_NOT_RESOLVED", message: "Slip is not resolved." }, 409));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/Analysis refused/);
  expect(alert.textContent).toMatch(/Slip is not resolved/);
});

test("slip that intake did not save cannot be analysed", () => {
  mount({ intake: { ...resolved, bet_slip_id: null } });
  expect(screen.getByText(/was not saved by the intake service/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Run analysis" })).toBeNull();
});

test("saved analysis reloads by id, using the market title when no slip is open", async () => {
  const fetch = stubFetch(json(success));
  mount({ intake: undefined, analysisId: ANALYSIS_ID });
  expect(screen.getByRole("status").textContent).toMatch(/Loading saved analysis/);
  expect(await screen.findByText("CONSIDER")).toBeTruthy();
  expect(fetch.mock.calls[0]?.[0]).toBe(`/api/v1/analyses/${ANALYSIS_ID}`);
  expect(region("Probability versus price").textContent).toContain("Chiefs to beat Bills");
});

test("saved analysis: unknown id is final, outage can retry", async () => {
  stubFetch(json({ code: "NOT_FOUND", message: "No analysis x." }, 404));
  mount({ intake: undefined, analysisId: ANALYSIS_ID });
  expect((await screen.findByRole("alert")).textContent).toMatch(/No saved analysis with that id/);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  cleanup();

  const fetch = stubFetch(json({}, 503), json(success));
  mount({ intake: undefined, analysisId: ANALYSIS_ID });
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("CONSIDER")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("INSUFFICIENT_DATA shows reasons and invents no numbers", async () => {
  stubFetch(json(noData));
  mount({ intake: undefined, analysisId: ANALYSIS_ID });
  await screen.findByText("INSUFFICIENT_DATA");
  const recommendation = region("Recommendation");
  expect(within(recommendation).getAllByText(/no features were available/).length).toBeGreaterThan(
    0,
  );
  const row = within(region("Probability versus price")).getAllByRole("row")[1] as HTMLElement;
  expect(within(row).getAllByText("Not available")).toHaveLength(3); // consensus, model, edge
  expect(region("Expected value").textContent).toContain("Expected value not computed.");
  expect(region("Evidence and paper trade").textContent).toContain("nothing here is sourced");
  // The only figure on the page is the market's own implied probability.
  expect(document.body.textContent?.match(/\d+\.\d%/g)).toEqual(["56.0%"]);
});

test("stale analysis and stale provider data are flagged", async () => {
  const record = withRecord(success, {
    provider_failures: [
      {
        provider: "weather",
        kind: "UNAVAILABLE",
        message: "[STALE] forecast is 9 h old",
        occurred_at: "2026-09-21T14:01:00Z",
      },
    ],
  });
  stubFetch(json(record));
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at("2026-09-21T14:40:00Z") });
  expect(await screen.findByText(/Stale: this analysis is 35 min old/)).toBeTruthy();
  const problems = screen.getByRole("region", { name: /Partial result: 1 source call failed/ });
  expect(within(problems).getByText("STALE")).toBeTruthy();
  expect(problems.textContent).toContain("forecast is 9 h old");
  expect(problems.textContent).not.toContain("[STALE]");
});

test("provider partial failure is explicit and keeps the rest of the analysis", async () => {
  const record = withRecord(success, {
    provider_failures: [
      {
        provider: "odds-api",
        kind: "RATE_LIMITED",
        message: "429 from provider",
        occurred_at: "2026-09-21T14:01:00Z",
      },
      {
        provider: "news-feed",
        kind: "TIMEOUT",
        message: "timed out",
        occurred_at: "2026-09-21T14:01:30Z",
      },
    ],
  });
  stubFetch(json(record));
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at(AS_OF) });
  const problems = await screen.findByRole("region", {
    name: /Partial result: 2 source calls failed/,
  });
  expect(problems.textContent).toContain("odds-api");
  expect(problems.textContent).toContain("RATE_LIMITED");
  expect(problems.textContent).toContain("missing, not assumed");
  expect(screen.getByText("CONSIDER")).toBeTruthy();
});

test("conflicting evidence is surfaced with both sides and opens in the drawer with provenance", async () => {
  const record = withRecord(success, {
    evidence_snapshots: [
      {
        ...success.evidence_snapshots[0],
        items: [item("1", "QB is active.", "ESPN"), item("2", "QB is out.", "Local Beat", "RUMOR")],
      },
    ],
  } as Partial<AnalysisRecord>);
  stubFetch(json(record));
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at(AS_OF) });
  const conflict = await screen.findByRole("region", { name: /Conflicting evidence/ });
  expect(conflict.textContent).toContain("QB is active.");
  expect(conflict.textContent).toContain("QB is out.");

  const dialog = document.querySelector("dialog") as HTMLDialogElement;
  const card = within(dialog).getAllByRole("listitem", { hidden: true })[1] as HTMLElement;
  expect(card.textContent).toContain("Rumor");
  expect(card.textContent).toContain("Local Beat");
  expect(card.textContent).toContain("2026-09-21 12:00 UTC"); // published
  expect(card.textContent).toContain("2026-09-21 13:55 UTC"); // retrieved
  expect(card.textContent).toContain("10 min before cutoff");
  expect(card.textContent).toContain("news-feed");
  const link = within(card).getByRole("link", { name: "Local Beat", hidden: true });
  expect(link.getAttribute("href")).toBe("https://example.com/Local-Beat");
  expect(link.getAttribute("rel")).toContain("noopener");
});

test("evidence sources that are not web links are not rendered as links", async () => {
  const bad = item("3", "Fact.", "Odd");
  bad.source.url = "javascript:alert(1)";
  stubFetch(
    json(
      withRecord(success, {
        evidence_snapshots: [{ ...success.evidence_snapshots[0], items: [bad] }],
      } as Partial<AnalysisRecord>),
    ),
  );
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at(AS_OF) });
  await screen.findByText("CONSIDER");
  expect(document.querySelector("dialog a")).toBeNull();
});

test("combo shows the labelled naive baseline, unquantified joint, and warnings", async () => {
  const two = {
    ...success.analysis,
    combo: {
      naive_baseline: {
        probability: "0.3136",
        label: "NAIVE_INDEPENDENT_BASELINE",
        assumption: "treats legs as independent; wrong whenever legs share a dependency",
      },
      warnings: [
        {
          kind: "SHARED_GAME",
          leg_indices: [0, 1],
          explanation: "Both legs depend on one game.",
          magnitude: "UNQUANTIFIED",
        },
      ],
      joint_probability: { reasons: ["no joint model exists"], status: "INSUFFICIENT_DATA" },
    },
  };
  stubFetch(json(withRecord(success, { analysis: two } as Partial<AnalysisRecord>)));
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at(AS_OF) });
  const combo = await screen.findByRole("region", { name: "Combo and correlation" });
  expect(combo.textContent).toContain("Naive independent baseline");
  expect(combo.textContent).toContain("31.4%");
  expect(combo.textContent).toContain("treats legs as independent");
  expect(combo.textContent).toContain("Not estimated: no joint model exists");
  expect(combo.textContent).toContain("SHARED_GAME");
  expect(combo.textContent).toContain("legs 1, 2");
  expect(combo.textContent).toContain("size unquantified");
});

test("paper trade stays disabled and says why", async () => {
  stubFetch(json(success));
  mount({ intake: undefined, analysisId: ANALYSIS_ID, now: at(AS_OF) });
  await screen.findByText("CONSIDER");
  const button = screen.getByRole("button", { name: "Record paper trade" });
  expect(button.getAttribute("aria-disabled")).toBe("true");
  expect(
    document.getElementById(button.getAttribute("aria-describedby") ?? "")?.textContent,
  ).toMatch(/paper-trade endpoint does not exist yet/);
});

test("without a slip or id the workspace offers to open a saved analysis", async () => {
  const onBack = vi.fn();
  const onOpen = mount({ intake: { ...resolved, state: "NEEDS_RESOLUTION", slip: null }, onBack });
  expect(screen.getByText(/No resolved slip in this tab/)).toBeTruthy();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Go to New analysis" }));
  expect(onBack).toHaveBeenCalled();

  await user.type(screen.getByLabelText(/Saved analysis id/), "nope");
  expect(screen.getByText("That is not an analysis id.")).toBeTruthy();
  await user.clear(screen.getByLabelText(/Saved analysis id/));
  await user.type(screen.getByLabelText(/Saved analysis id/), ANALYSIS_ID);
  await user.click(screen.getByRole("button", { name: "Open saved analysis" }));
  expect(onOpen).toHaveBeenCalledWith(ANALYSIS_ID);
});

test("route with ?id= reloads the saved analysis and nav keeps aria-current", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(url.startsWith("/api/v1/analyses/") ? json(success) : json({}, 503)),
    ),
  );
  history.replaceState(null, "", `/analysis?id=${ANALYSIS_ID}`);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <App />
    </QueryClientProvider>,
  );
  const nav = screen.getByRole("navigation", { name: "Primary" });
  expect(
    within(nav).getByRole("link", { name: "Analysis workspace" }).getAttribute("aria-current"),
  ).toBe("page");
  expect(await screen.findByText("CONSIDER")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Go to New analysis" }));
  expect(location.pathname).toBe("/");
  expect(location.search).toBe("");
});
