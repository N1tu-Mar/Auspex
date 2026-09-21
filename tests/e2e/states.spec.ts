import { expect, type Page, test } from "@playwright/test";
import { legGroup, MANUAL_URL, PASTE_URL, paste, resolveSingleMarket } from "./support";

test.use({ timezoneId: "UTC" });

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

const panel = (page: Page) => page.getByRole("complementary", { name: "Intake check" });

test("empty state tells the user how to start", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Legs (0)" })).toBeVisible();
  await expect(
    page.getByText("No legs yet. Parse pasted text or add a leg by hand."),
  ).toBeVisible();
  await expect(panel(page).getByText(/^Nothing checked yet/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Resolved slip" })).toHaveCount(0);
});

test("loading is announced and blocks duplicate submits until the API answers", async ({
  page,
}) => {
  let release = () => {};
  const gate = new Promise<void>((done) => {
    release = done;
  });
  await page.route(PASTE_URL, async (route) => {
    await gate;
    await route.continue();
  });

  await paste(page, "Chiefs ML @ 0.56");
  await expect(page.getByRole("status")).toHaveText("Checking with the intake service…");
  await expect(page.getByRole("button", { name: "Parsing…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Check legs" })).toBeDisabled();

  release();
  await expect(legGroup(page, 1).getByText("No known event matches Chiefs.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Parse into legs" })).toBeEnabled();
  await expect(page.getByText("Checking with the intake service…")).toHaveCount(0);
});

test("editing after a check marks the result stale until checked again", async ({ page }) => {
  await resolveSingleMarket(page);
  const leg = legGroup(page, 1);
  await leg.getByLabel("Price (USD)").fill("0.6");

  const stale = page.getByRole("alert").filter({ hasText: "Out of date." });
  await expect(stale).toBeVisible();
  await expect(page.getByRole("region", { name: "Resolved slip" })).toHaveCount(0);
  await expect(leg.getByText("Resolved before edits")).toBeVisible();

  await page.getByRole("button", { name: "Check legs" }).click();
  await expect(stale).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Resolved slip" }).getByRole("row").nth(1),
  ).toContainText("0.6");
});

test("a failed re-check keeps the earlier resolved result and the user's input", async ({
  page,
}) => {
  await resolveSingleMarket(page);
  const firstTrace = await panel(page)
    .getByText(/ · trace /)
    .textContent();

  await page.route(MANUAL_URL, (route) => route.fulfill({ status: 503, body: "upstream timeout" }));
  await page.getByRole("button", { name: "Check legs" }).click();

  const failure = page.getByRole("alert").filter({ hasText: "Intake service unavailable" });
  await expect(failure).toContainText("HTTP 503 without a result");
  await expect(failure).toContainText("Your legs are kept.");
  // Earlier successful result stays on screen and the form is untouched.
  await expect(page.getByRole("region", { name: "Resolved slip" })).toBeVisible();
  await expect(panel(page).getByText(/ · trace /)).toHaveText(firstTrace ?? "");
  await expect(legGroup(page, 1).getByLabel("Event ID")).toHaveValue("qa-nfl-kc-buf");

  await page.unroute(MANUAL_URL);
  await failure.getByRole("button", { name: "Try again" }).click();
  await expect(failure).toHaveCount(0);
  await expect(panel(page).getByText(/ · trace /)).not.toHaveText(firstTrace ?? "");
  await expect(page.getByRole("region", { name: "Resolved slip" })).toBeVisible();
});

test("an unreachable service keeps pasted text and can be retried", async ({ page }) => {
  await page.route(PASTE_URL, (route) => route.abort("connectionrefused"));
  await paste(page, "Chiefs ML @ 0.56");

  const failure = page.getByRole("alert").filter({ hasText: "Intake service unavailable" });
  await expect(failure).toContainText("Could not reach the intake service.");
  await expect(page.getByLabel("Slip text")).toHaveValue("Chiefs ML @ 0.56");

  await page.unroute(PASTE_URL);
  await failure.getByRole("button", { name: "Try again" }).click();
  await expect(legGroup(page, 1).getByText("No known event matches Chiefs.")).toBeVisible();
});

// Not built yet: evidence collection has no API or UI. Tracked so the gap stays visible.
test.fixme("conflicting evidence is flagged with both sources", async () => {});
test.fixme("one evidence provider failing keeps evidence from the others", async () => {});
