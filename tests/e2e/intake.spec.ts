import { expect, test } from "@playwright/test";
import { fillLeg, intakeCalls, KC_BUF_ML, legGroup, paste, servePaste } from "./support";

test.use({ timezoneId: "UTC" });

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

const panel = (page: import("@playwright/test").Page) =>
  page.getByRole("complementary", { name: "Intake check" });

test("single pasted market resolves and its slip can be reviewed", async ({ page }) => {
  await paste(page, "Chiefs ML @ 0.56");
  const leg = legGroup(page, 1);
  await expect(leg.getByText("Pasted: Chiefs ML @ 0.56")).toBeVisible();
  await expect(leg.getByLabel("Market type")).toHaveValue("MONEYLINE");
  await expect(leg.getByLabel("Price (USD)")).toHaveValue("0.56");
  // Unknown values are left blank, not guessed.
  await expect(leg.getByLabel("Side")).toHaveValue("");
  await expect(leg.getByLabel("Event ID")).toHaveValue("");
  await expect(panel(page).getByText("Needs resolution", { exact: true })).toBeVisible();

  await fillLeg(leg, KC_BUF_ML);
  await page.getByRole("button", { name: "Check legs" }).click();

  const slip = page.getByRole("region", { name: "Resolved slip" });
  await expect(panel(page).getByText("Resolved", { exact: true })).toBeVisible();
  await expect(panel(page).getByText(/· manual · trace /)).toBeVisible();
  const rows = slip.getByRole("row");
  await expect(rows).toHaveCount(4); // header, one leg, stake, payout
  const cells = rows.nth(1).getByRole("cell");
  await expect(cells.nth(0)).toContainText("Buffalo Bills at Kansas City Chiefs");
  await expect(cells.nth(0)).toContainText("NFL · 2030-09-29 00:20 UTC");
  await expect(cells.nth(1)).toHaveText("Moneyline · Home");
  await expect(cells.nth(2)).toHaveText("—");
  await expect(cells.nth(3)).toHaveText("0.56");
  await expect(slip.getByRole("row", { name: /Stake \(USD\)/ })).toContainText("25");
  await expect(slip.getByRole("row", { name: /Quoted gross payout/ })).toContainText("Not quoted");
  await slip.getByRole("button", { name: "Open analysis workspace" }).click();
  await expect(page).toHaveURL(/\/analysis$/);
  await expect(page.getByRole("button", { name: "Run analysis" })).toBeVisible();
});

test("pasted combo keeps every leg separate, including one it cannot parse", async ({ page }) => {
  await paste(
    page,
    "Chiefs ML @ 0.56; Bills/Chiefs over 47.5 @ .51 + Chiefs -3.5 @ 0.52\nChiefs to win big",
  );
  const expected = [
    { raw: "Chiefs ML @ 0.56", market: "MONEYLINE", line: "", price: "0.56", side: "" },
    {
      raw: "Bills/Chiefs over 47.5 @ .51",
      market: "TOTAL",
      line: "47.5",
      price: "0.51",
      side: "OVER",
    },
    { raw: "Chiefs -3.5 @ 0.52", market: "SPREAD", line: "-3.5", price: "0.52", side: "" },
  ];
  await expect(page.getByRole("heading", { name: "Legs (4)" })).toBeVisible();
  for (const [i, leg] of expected.entries()) {
    const group = legGroup(page, i + 1);
    await expect(group.getByText(`Pasted: ${leg.raw}`)).toBeVisible();
    await expect(group.getByLabel("Market type")).toHaveValue(leg.market);
    await expect(group.getByLabel("Line", { exact: true })).toHaveValue(leg.line);
    await expect(group.getByLabel("Price (USD)")).toHaveValue(leg.price);
    await expect(group.getByLabel("Side")).toHaveValue(leg.side);
    await expect(group.getByText(/^No known event matches/)).toBeVisible();
  }
  const unparsed = legGroup(page, 4);
  await expect(unparsed.getByText("Pasted: Chiefs to win big")).toBeVisible();
  await expect(unparsed.getByText("UNPARSEABLE_LEG")).toBeVisible();
  await expect(unparsed.getByLabel("Market type")).toHaveValue("");
  await expect(panel(page).getByText("4 needs resolution")).toBeVisible();
});

test("resolved combo shows every leg in the review table", async ({ page }) => {
  const { body, requests } = await servePaste(page, "paste-combo.json");
  await paste(page, body.original_input, "1.00", "3.50");
  expect(requests).toEqual([
    { text: body.original_input, stake_usd: "1.00", gross_payout_usd: "3.50" },
  ]);

  const slip = page.getByRole("region", { name: "Resolved slip" });
  await expect(slip).toBeVisible();
  const legs = [
    { market: "Moneyline · Home", line: "—", price: "0.56", side: "HOME" },
    { market: "Total · Over", line: "47.5", price: "0.51", side: "OVER" },
  ];
  for (const [i, leg] of legs.entries()) {
    const cells = slip
      .getByRole("row")
      .nth(i + 1)
      .getByRole("cell");
    await expect(cells.nth(0)).toContainText("Buffalo Bills at Kansas City Chiefs");
    await expect(cells.nth(1)).toHaveText(leg.market);
    await expect(cells.nth(2)).toHaveText(leg.line);
    await expect(cells.nth(3)).toHaveText(leg.price);
    const group = legGroup(page, i + 1);
    await expect(group.getByText("Resolved", { exact: true })).toBeVisible();
    await expect(group.getByLabel("Event ID")).toHaveValue("qa-nfl-kc-buf");
    await expect(group.getByLabel("Side")).toHaveValue(leg.side);
  }
  await expect(slip.getByRole("row", { name: /Quoted gross payout/ })).toContainText("3.50");

  // The real API accepts the slip exactly as the UI now holds it.
  await page.getByRole("button", { name: "Check legs" }).click();
  await expect(panel(page).getByText(/· manual · trace /)).toBeVisible();
  await expect(panel(page).getByText("2 resolved")).toBeVisible();
});

test("ambiguous event is corrected by choosing a candidate", async ({ page }) => {
  const { body } = await servePaste(page, "paste-ambiguous.json");
  await paste(page, body.original_input, "1.00");
  const leg = legGroup(page, 1);
  const choices = leg.getByRole("group", { name: /2 events match/ });
  await expect(choices.getByRole("radio")).toHaveCount(2);
  for (const radio of await choices.getByRole("radio").all()) await expect(radio).not.toBeChecked();
  await expect(leg.getByLabel("Event ID")).toHaveValue("");
  await expect(leg.getByLabel("Event ID")).toHaveAccessibleDescription(
    "2 events match; choose one. (AMBIGUOUS_EVENT)",
  );

  await choices.getByRole("radio", { name: /Philadelphia Eagles at New York Giants/ }).check();
  await expect(leg.getByLabel("Event ID")).toHaveValue("qa-nfl-nyg-phi");
  await expect(leg.getByLabel("Home", { exact: true })).toHaveValue("New York Giants");
  await expect(leg.getByLabel("Away", { exact: true })).toHaveValue("Philadelphia Eagles");
  await expect(leg.getByLabel("Event start (local time)")).toHaveValue("2030-10-06T17:00");
  await expect(leg.getByLabel("Sport")).toHaveValue("NFL");

  await fillLeg(leg, { Side: "HOME", "Settlement rule reference": "qa-nfl-ml" });
  await page.getByRole("button", { name: "Check legs" }).click();
  const slip = page.getByRole("region", { name: "Resolved slip" });
  await expect(slip.getByRole("row").nth(1)).toContainText(
    "Philadelphia Eagles at New York Giants",
  );
});

test("invalid input is caught in the browser without calling the API", async ({ page }) => {
  const calls = intakeCalls(page);
  await page.getByRole("button", { name: "Parse into legs" }).click();
  await expect(page.getByText("Paste at least one leg, e.g. Chiefs ML @ 0.56.")).toBeVisible();

  await page.getByRole("button", { name: "Add leg" }).click();
  const leg = legGroup(page, 1);
  await leg.getByLabel("Price (USD)").fill("1.5");
  await page.getByLabel("Stake (USD)").fill("-4");
  await page.getByRole("button", { name: "Check legs" }).click();

  await expect(leg.getByLabel("Price (USD)")).toHaveAttribute("aria-invalid", "true");
  await expect(leg.getByLabel("Price (USD)")).toHaveAccessibleDescription(
    /Price must be above 0 and below 1 USD/,
  );
  await expect(page.getByLabel("Stake (USD)")).toHaveAccessibleDescription(
    /Stake must be a positive USD amount/,
  );
  await expect(leg.getByLabel("Sport")).toHaveAccessibleDescription("Choose a sport.");
  expect(calls).toEqual([]);
});

test("the API's validation failures are shown on the leg", async ({ page }) => {
  await paste(page, "Chiefs ML @ 1.5");
  const leg = legGroup(page, 1);
  await expect(panel(page).getByText("Rejected", { exact: true })).toBeVisible();
  await expect(leg.getByText("MALFORMED_INPUT")).toBeVisible();
  await expect(leg.getByText("Price must be in (0, 1) USD.")).toBeVisible();
});

test("unsupported markets are rejected with the pregame-only reason", async ({ page }) => {
  await page.getByRole("button", { name: "Add leg" }).click();
  const leg = legGroup(page, 1);
  await page.getByLabel("Stake (USD)").fill("10");
  await fillLeg(leg, {
    ...KC_BUF_ML,
    "Market type": "MONEYLINE",
    "Price (USD)": "0.56",
    "Market status": "LIVE",
  });
  const check = page.getByRole("button", { name: "Check legs" });
  const pregameOnly = panel(page).getByText(/Only pregame markets are supported/);

  await check.click();
  await expect(pregameOnly).toBeVisible();
  await expect(leg.getByLabel("Market status")).toHaveAccessibleDescription(
    "LIVE legs are not supported. (UNSUPPORTED_STATUS)",
  );

  await fillLeg(leg, {
    "Market status": "PREGAME",
    "Event start (local time)": "2020-01-05T18:00",
  });
  await check.click();
  await expect(leg.getByText("Event has started; only pregame is supported.")).toBeVisible();
  await expect(pregameOnly).toBeVisible();

  await fillLeg(leg, { "Event start (local time)": "2030-09-29T00:20", Side: "DRAW" });
  await check.click();
  await expect(leg.getByLabel("Side")).toHaveAccessibleDescription(
    "DRAW is invalid for MONEYLINE. (INVALID_SIDE)",
  );
  await expect(panel(page).getByText("Rejected", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Resolved slip" })).toHaveCount(0);
});
