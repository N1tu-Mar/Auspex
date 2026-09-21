import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";

export const PASTE_URL = "**/api/v1/bet-slips/intake/paste";
export const MANUAL_URL = "**/api/v1/bet-slips/intake/manual";

// Paste fixtures are proven identical to real intake output by tests/integration.
export function fixture(name: string) {
  return JSON.parse(readFileSync(resolve("tests/e2e/fixtures", name), "utf8"));
}

/** Serve a paste fixture in place of the API (the production catalog is empty). */
export async function servePaste(page: Page, name: string) {
  const body = fixture(name);
  const requests: Record<string, unknown>[] = [];
  await page.route(PASTE_URL, async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ json: body });
  });
  return { body, requests };
}

/** Count intake calls so tests can prove nothing was sent. */
export function intakeCalls(page: Page) {
  const urls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/bet-slips/intake/")) urls.push(request.url());
  });
  return urls;
}

const SELECTS = new Set(["Sport", "Market status", "Market type", "Side"]);

export async function fillLeg(leg: Locator, values: Record<string, string>) {
  for (const [label, value] of Object.entries(values)) {
    const control = leg.getByLabel(label, { exact: true });
    if (SELECTS.has(label)) await control.selectOption(value);
    else await control.fill(value);
  }
}

export const legGroup = (page: Page, n: number) =>
  page.getByRole("group", { name: `Leg ${n}`, exact: true });

/** Fields the real catalog cannot supply yet, for Chiefs ML against Bills. */
export const KC_BUF_ML = {
  Sport: "NFL",
  League: "NFL",
  "Event start (local time)": "2030-09-29T00:20",
  Home: "Kansas City Chiefs",
  Away: "Buffalo Bills",
  "Event ID": "qa-nfl-kc-buf",
  Side: "HOME",
  "Settlement rule reference": "qa-nfl-ml",
};

export async function paste(page: Page, text: string, stake = "25", payout = "") {
  await page.getByLabel("Slip text").fill(text);
  await page.getByLabel("Stake (USD)").fill(stake);
  await page.getByLabel("Quoted gross payout (USD, optional)").fill(payout);
  await page.getByRole("button", { name: "Parse into legs" }).click();
}

/** Real-API path: paste one leg, complete it by hand, check it until RESOLVED. */
export async function resolveSingleMarket(page: Page) {
  await paste(page, "Chiefs ML @ 0.56");
  await expect(legGroup(page, 1).getByText("No known event matches Chiefs.")).toBeVisible();
  await fillLeg(legGroup(page, 1), KC_BUF_ML);
  await page.getByRole("button", { name: "Check legs" }).click();
  await expect(page.getByRole("region", { name: "Resolved slip" })).toBeVisible();
}
