import { expect, test } from "@playwright/test";
import { legGroup, PASTE_URL, servePaste } from "./support";

test.use({ timezoneId: "UTC" });

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("page exposes named landmarks and headings", async ({ page }) => {
  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Auspex" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "New analysis" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Intake check" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Paste a slip" })).toBeVisible();
});

test("every leg control has an accessible name", async ({ page }) => {
  await page.getByRole("button", { name: "Add leg" }).click();
  const leg = legGroup(page, 1);
  const labels = [
    "Sport",
    "League",
    "Event start (local time)",
    "Market status",
    "Home",
    "Away",
    "Event ID",
    "Player ID (props)",
    "Market type",
    "Side",
    "Line",
    "Price (USD)",
    "Polymarket market ID",
    "Settlement rule reference",
  ];
  for (const label of labels) await expect(leg.getByLabel(label, { exact: true })).toHaveCount(1);
  for (const name of ["Sport", "Market status", "Market type", "Side"]) {
    await expect(leg.getByRole("combobox", { name, exact: true })).toBeVisible();
  }
  await expect(leg.getByRole("button", { name: "Remove leg 1" })).toBeVisible();
});

test("paste flow works from the keyboard alone", async ({ page }) => {
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Slip text")).toBeFocused();
  await page.keyboard.type("Chiefs ML @ 0.56");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Stake (USD)")).toBeFocused();
  await page.keyboard.type("25");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Quoted gross payout (USD, optional)")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Parse into legs" })).toBeFocused();
  await page.keyboard.press("Enter");

  const leg = legGroup(page, 1);
  await expect(leg.getByText("No known event matches Chiefs.")).toBeVisible();
  await page.getByRole("button", { name: "Add leg" }).focus();
  await page.keyboard.press("Tab");
  await expect(leg.getByRole("button", { name: "Remove leg 1" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(leg.getByLabel("Sport")).toBeFocused();

  // Enter in a field submits the check; the first invalid field receives focus.
  await leg.getByLabel("Price (USD)").press("Enter");
  await expect(leg.getByLabel("Sport")).toBeFocused();
  await expect(leg.getByLabel("Sport")).toHaveAccessibleDescription("Choose a sport.");
});

test("ambiguous candidates can be chosen with arrow keys", async ({ page }) => {
  const { body } = await servePaste(page, "paste-ambiguous.json");
  await page.getByLabel("Slip text").fill(body.original_input);
  await page.getByLabel("Stake (USD)").fill("1.00");
  await page.getByRole("button", { name: "Parse into legs" }).press("Enter");

  const leg = legGroup(page, 1);
  const radios = leg.getByRole("group", { name: /2 events match/ }).getByRole("radio");
  await radios.first().focus();
  await page.keyboard.press("Space");
  await expect(leg.getByLabel("Event ID")).toHaveValue("qa-nfl-nyg-dal");
  await page.keyboard.press("ArrowDown");
  await expect(radios.nth(1)).toBeChecked();
  await expect(leg.getByLabel("Event ID")).toHaveValue("qa-nfl-nyg-phi");
});

// Known defect, see docs/workstreams/requests/qa-frontend-keyboard-focus-after-submit.md.
// test.fail flips to a failure once fixed, as a reminder to drop the marker.
test("keyboard focus survives a submit", async ({ page }) => {
  test.fail();
  let release = () => {};
  const gate = new Promise<void>((done) => {
    release = done;
  });
  await page.route(PASTE_URL, async (route) => {
    await gate;
    await route.continue();
  });
  await page.getByLabel("Slip text").fill("Chiefs ML @ 0.56");
  await page.getByLabel("Stake (USD)").fill("25");
  await page.getByRole("button", { name: "Parse into legs" }).press("Enter");
  // Hold the request so the pending (disabled) render always happens before the answer.
  await expect(page.getByText("Checking with the intake service…")).toBeVisible();
  release();
  await expect(legGroup(page, 1).getByText("No known event matches Chiefs.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Parse into legs" })).toBeFocused({
    timeout: 1_000,
  });
});
