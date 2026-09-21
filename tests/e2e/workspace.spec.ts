import { expect, type Page, test } from "@playwright/test";
import { paste, resolveSingleMarket, SAVED_SLIP_ID, serveAnalysis, servePaste } from "./support";

test.use({ timezoneId: "UTC" });

// Fixtures are cut at 2026-09-21 12:00 UTC. Pin the browser clock a minute later so the
// stale-analysis banner only appears when a test asks for it.
const FRESH = new Date("2026-09-21T12:01:00Z");

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FRESH);
  await page.goto("/");
});

const recommendation = (page: Page) => page.getByRole("region", { name: "Recommendation" });

/** Resolve one leg through the real intake API, then run the analysis the fixture answers. */
async function runSingle(page: Page, scenario: string) {
  const served = await serveAnalysis(page, scenario);
  await resolveSingleMarket(page);
  await page.getByRole("button", { name: "Open analysis workspace" }).click();
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(recommendation(page)).toBeVisible();
  return served;
}

async function runCombo(page: Page) {
  const served = await serveAnalysis(page, "combo");
  const { body } = await servePaste(page, "paste-combo.json", { bet_slip_id: SAVED_SLIP_ID });
  await paste(page, body.original_input, "1.00", "3.50");
  await page.getByRole("button", { name: "Open analysis workspace" }).click();
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(recommendation(page)).toBeVisible();
  return served;
}

test("running an analysis sends the saved slip id and never assumes fees", async ({ page }) => {
  const { posts, id } = await runSingle(page, "nodata");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toEqual({ bet_slip_id: expect.stringMatching(/^[0-9a-f-]{36}$/) });
  await expect(page).toHaveURL(new RegExp(`/analysis\\?id=${id}$`));
  await expect(recommendation(page)).toContainText("INSUFFICIENT_DATA");
  await expect(page.getByText("Expected value not computed.")).toBeVisible();
});

test("fees and slippage are validated before anything is sent", async ({ page }) => {
  const { posts } = await serveAnalysis(page, "nodata");
  await resolveSingleMarket(page);
  await page.getByRole("button", { name: "Open analysis workspace" }).click();
  await page.getByLabel("Estimated fees (USD, optional)").fill("abc");
  await expect(page.getByText("Use dollars and cents, like 0.50.")).toBeVisible();
  await page.getByLabel("Estimated fees (USD, optional)").press("Enter");
  await expect(page.getByRole("button", { name: "Run analysis" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  expect(posts).toHaveLength(0);
  await page.getByLabel("Estimated fees (USD, optional)").fill("0.10");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(recommendation(page)).toBeVisible();
  expect(posts[0]).toMatchObject({ estimated_fees_usd: "0.10" });
});

test("no evidence: the workspace says nothing here is sourced", async ({ page }) => {
  await runSingle(page, "nodata");
  const panel = page.getByRole("region", { name: "Evidence and paper trade" });
  await expect(panel).toContainText("No evidence was collected, so nothing here is sourced.");
  await expect(panel.getByRole("button", { name: "Open evidence (0)" })).toBeVisible();
});

test("evidence shows publisher link, retrieval time, and age to the cutoff", async ({ page }) => {
  await runSingle(page, "evidence");
  await page.getByRole("button", { name: "Open evidence (1)" }).click();
  const dialog = page.getByRole("dialog", { name: "Evidence" });
  await expect(dialog.getByText("Starter is questionable.")).toBeVisible();
  const link = dialog.getByRole("link", { name: "wire publisher" });
  await expect(link).toHaveAttribute("href", "https://wire.example/a");
  await expect(link).toHaveAttribute("rel", /noopener/);
  await expect(dialog.getByText(/2026-09-21 11:55 UTC · 5 min before cutoff/)).toBeVisible();
  await expect(dialog.getByText("Rumor", { exact: true })).toBeVisible();
});

test("conflicting evidence is flagged and both sources are kept", async ({ page }) => {
  await runSingle(page, "conflict");
  const notice = page.getByRole("region", { name: "Conflicting evidence: sources disagree" });
  await expect(notice).toContainText("Starter is out.");
  await expect(notice).toContainText("Starter will play.");
  await expect(notice).toContainText("north publisher");
  await expect(notice).toContainText("south publisher");
  await page.getByRole("button", { name: "Open evidence (2)" }).click();
  const dialog = page.getByRole("dialog", { name: "Evidence" });
  await expect(dialog.getByRole("link", { name: "north publisher" })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "south publisher" })).toBeVisible();
});

test("one provider failing keeps evidence from the others and says what is missing", async ({
  page,
}) => {
  await runSingle(page, "partial");
  const problems = page.getByRole("region", { name: /Partial result: 1 source call failed/ });
  await expect(problems).toContainText("down");
  await expect(problems).toContainText("TIMEOUT");
  await expect(problems).toContainText("no response in 5s");
  await expect(problems).toContainText("missing, not assumed");
  await page.getByRole("button", { name: "Open evidence (1)" }).click();
  await expect(
    page.getByRole("dialog", { name: "Evidence" }).getByText("Dry field."),
  ).toBeVisible();
});

test("stale evidence is reported as too old and the recommendation stays INSUFFICIENT_DATA", async ({
  page,
}) => {
  await runSingle(page, "stale");
  const problems = page.getByRole("region", { name: /Partial result/ });
  await expect(problems).toContainText("STALE");
  await expect(problems).toContainText("1 returned data too old to use (stale).");
  await expect(recommendation(page)).toContainText("INSUFFICIENT_DATA");
  await page.getByRole("button", { name: "Open evidence (0)" }).click();
  await expect(
    page.getByRole("dialog", { name: "Evidence" }).getByText("No evidence was collected"),
  ).toBeVisible();
});

test("an old analysis is labelled stale", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-09-21T12:30:00Z"));
  await runSingle(page, "nodata");
  await expect(
    page.getByRole("status").filter({ hasText: "Stale: this analysis is" }),
  ).toBeVisible();
});

test("unsupported model coverage names the reason for the leg", async ({ page }) => {
  await runSingle(page, "unsupported");
  await expect(page.getByRole("listitem").filter({ hasText: "Leg 1, no estimate:" })).toContainText(
    "no model coverage for SOCCER",
  );
  await expect(recommendation(page)).toContainText("INSUFFICIENT_DATA");
  const table = page.getByRole("table");
  await expect(table.getByRole("cell", { name: "Not available" })).toHaveCount(3);
});

test("combo shows correlation warnings and no joint probability", async ({ page }) => {
  await runCombo(page);
  const combo = page.getByRole("region", { name: "Combo and correlation" });
  await expect(combo).toContainText("SHARED_GAME");
  await expect(combo).toContainText("legs 1, 2: both legs settle on the same game");
  await expect(combo).toContainText("(size unquantified)");
  await expect(combo).toContainText("Naive independent baseline");
  await expect(combo).toContainText("Not estimated: 3 shared-dependency warning(s)");
  await expect(recommendation(page)).toContainText("INSUFFICIENT_DATA");
});

test("single leg has no combo to assess", async ({ page }) => {
  await runSingle(page, "nodata");
  await expect(page.getByText("Single leg: no combo to assess.")).toBeVisible();
});

test("failed analysis keeps the form and retry works", async ({ page }) => {
  await resolveSingleMarket(page);
  await page.getByRole("button", { name: "Open analysis workspace" }).click();
  await page.route("**/api/v1/analyses", (route) => route.fulfill({ status: 503, body: "" }));
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByRole("alert")).toContainText("Analysis did not complete");
  await page.unroute("**/api/v1/analyses");
  await serveAnalysis(page, "nodata");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(recommendation(page)).toBeVisible();
});

test.describe("saved analysis id", () => {
  test("reloads the workspace after the analysis ran, from the URL alone", async ({ page }) => {
    const { id } = await runSingle(page, "conflict");
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`id=${id}$`));
    await expect(recommendation(page)).toContainText("INSUFFICIENT_DATA");
    await expect(
      page.getByRole("region", { name: "Conflicting evidence: sources disagree" }),
    ).toBeVisible();
  });

  test("opens in a fresh tab with no slip", async ({ browser }) => {
    const context = await browser.newContext({ timezoneId: "UTC" });
    const page = await context.newPage();
    await page.clock.setFixedTime(FRESH);
    const { id } = await serveAnalysis(page, "partial");
    await page.goto(`/analysis?id=${id}`);
    await expect(recommendation(page)).toBeVisible();
    await expect(page.getByRole("region", { name: /Partial result/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Go to New analysis" })).toBeVisible();
    await context.close();
  });

  test("open-by-id form rejects a non-id and opens a real one", async ({ page }) => {
    const { id } = await serveAnalysis(page, "nodata");
    await page.goto("/analysis");
    await expect(page.getByText(/No resolved slip in this tab/)).toBeVisible();
    await page.getByLabel("Saved analysis id").fill("nope");
    await expect(page.getByText("That is not an analysis id.")).toBeVisible();
    await page.getByLabel("Saved analysis id").fill(id);
    await page.getByRole("button", { name: "Open saved analysis" }).click();
    await expect(recommendation(page)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`id=${id}$`));
  });

  test("unknown id says so and offers no retry", async ({ page }) => {
    await serveAnalysis(page, "nodata");
    await page.goto("/analysis?id=00000000-0000-4000-8000-000000000000");
    await expect(page.getByRole("alert")).toContainText("No saved analysis with that id");
    await expect(page.getByRole("alert").getByRole("button", { name: "Retry" })).toHaveCount(0);
  });

  test("loading is announced", async ({ page }) => {
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { record, id } = await serveAnalysis(page, "nodata");
    await page.route("**/api/v1/analyses/*", async (route) => {
      await gate;
      await route.fulfill({ json: record });
    });
    await page.goto(`/analysis?id=${id}`);
    await expect(page.getByRole("status")).toContainText("Loading saved analysis");
    release();
    await expect(recommendation(page)).toBeVisible();
  });
});

test.describe("evidence disclosure", () => {
  test.beforeEach(async ({ page }) => {
    await runSingle(page, "evidence");
  });

  test("keyboard opens it, focus moves inside, Escape closes and returns focus", async ({
    page,
  }) => {
    const trigger = page.getByRole("button", { name: "Open evidence (1)" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Evidence" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("link", { name: "wire publisher" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("dialog is modal: Tab and Shift+Tab never reach the page behind it", async ({ page }) => {
    await page.getByRole("button", { name: "Open evidence (1)" }).click();
    const behind = [
      page.getByRole("button", { name: "Back to slip" }),
      page.getByRole("button", { name: "Record paper trade" }),
    ];
    for (const key of ["Tab", "Tab", "Shift+Tab", "Shift+Tab", "Tab"]) {
      await page.keyboard.press(key);
      for (const control of behind) await expect(control).not.toBeFocused();
    }
  });

  test("Close button closes it and returns focus", async ({ page }) => {
    await page.getByRole("button", { name: "Open evidence (1)" }).click();
    await page
      .getByRole("dialog", { name: "Evidence" })
      .getByRole("button", { name: "Close" })
      .click();
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByRole("button", { name: "Open evidence (1)" })).toBeFocused();
  });

  test("paper trade stays unavailable and says why", async ({ page }) => {
    const button = page.getByRole("button", { name: "Record paper trade" });
    await expect(button).toHaveAccessibleDescription(/paper-trade endpoint does not exist yet/);
    await expect(button).toHaveAttribute("aria-disabled", "true");
  });
});
