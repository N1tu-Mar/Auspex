import { expect, type Page, test } from "@playwright/test";
import { paste, resolveSingleMarket, servePaste } from "./support";

test.use({ timezoneId: "UTC" });

async function openWorkspace(page: Page) {
  await page
    .getByRole("region", { name: "Resolved slip" })
    .getByRole("button", { name: "Open analysis workspace" })
    .click();
  await expect(page.getByRole("heading", { name: "Analysis workspace" })).toBeVisible();
}

async function openComboWorkspace(page: Page) {
  const { body } = await servePaste(page, "paste-combo.json");
  await paste(page, body.original_input, "1.00", "3.50");
  await openWorkspace(page);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("no evidence is collected: the workspace abstains instead of inventing a claim", async ({
  page,
}) => {
  await resolveSingleMarket(page);
  await openWorkspace(page);
  await expect(page.getByRole("region", { name: "Recommendation" })).toContainText(
    "INSUFFICIENT_DATA",
  );
  await expect(page.getByRole("row", { name: /Not estimated/ })).toContainText("Not estimated");
  await expect(page.getByRole("region", { name: "Explanation and sources" })).toContainText(
    "No explanation yet.",
  );
  await expect(page.getByText(/Missing: evidence snapshot/)).toBeVisible();
});

test("combo warns that the joint probability is unknown, not independent", async ({ page }) => {
  await openComboWorkspace(page);
  const warnings = page.getByRole("region", { name: "Correlation warnings" });
  await expect(warnings).toContainText("Not checked.");
  await expect(warnings).toContainText(
    "treat the legs' joint probability as unknown, not independent",
  );
});

test("single leg has no combo caveat", async ({ page }) => {
  await resolveSingleMarket(page);
  await openWorkspace(page);
  await expect(page.getByRole("region", { name: "Correlation warnings" })).not.toContainText(
    "joint probability",
  );
});

test("workspace survives a reload in the same tab", async ({ page }) => {
  await resolveSingleMarket(page);
  await openWorkspace(page);
  await page.reload();
  await expect(page).toHaveURL(/\/analysis$/);
  await expect(page.getByRole("heading", { name: "Analysis workspace" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recommendation" })).toContainText(
    "INSUFFICIENT_DATA",
  );
});

test("a fresh tab has no slip and offers a way back", async ({ browser }) => {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/analysis");
  await expect(page.getByText(/No resolved slip in this tab/)).toBeVisible();
  await page.getByRole("button", { name: "Go to New analysis" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test.describe("evidence disclosure", () => {
  test.beforeEach(async ({ page }) => {
    await resolveSingleMarket(page);
    await openWorkspace(page);
  });

  test("keyboard opens it, focus moves inside, Escape closes and returns focus", async ({
    page,
  }) => {
    const trigger = page.getByRole("button", { name: "Open evidence" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Evidence" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("No evidence collected for this slip.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("dialog is modal: Tab and Shift+Tab never reach the page behind it", async ({ page }) => {
    await page.getByRole("button", { name: "Open evidence" }).click();
    const behind = [
      page.getByRole("button", { name: "Back to slip" }),
      page.getByRole("button", { name: "Record paper trade" }),
    ];
    for (const key of ["Tab", "Tab", "Shift+Tab", "Shift+Tab", "Tab"]) {
      await page.keyboard.press(key);
      for (const control of behind) await expect(control).not.toBeFocused();
    }
  });

  test("Close button closes it", async ({ page }) => {
    await page.getByRole("button", { name: "Open evidence" }).click();
    await page
      .getByRole("dialog", { name: "Evidence" })
      .getByRole("button", { name: "Close" })
      .click();
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByRole("button", { name: "Open evidence" })).toBeFocused();
  });

  test("paper trade stays unavailable and says why", async ({ page }) => {
    const button = page.getByRole("button", { name: "Record paper trade" });
    await expect(button).toHaveAccessibleDescription(
      /Unavailable: a paper trade records the model estimate/,
    );
    await expect(button).toHaveAttribute("aria-disabled", "true");
  });
});

// The API stores evidence, provider failures, and analysis ids (tests/integration/test_analysis_flow.py),
// but the web app never calls /api/v1/analyses. These stay fixme until it does.
test.describe("analysis UI not built", () => {
  test.fixme("evidence items show publisher, link, and retrieval time", async () => {});
  test.fixme("conflicting evidence is flagged with both sources", async () => {});
  test.fixme("one evidence provider failing keeps evidence from the others", async () => {});
  test.fixme("stale evidence is listed as dropped and the recommendation stays INSUFFICIENT_DATA", async () => {});
  test.fixme("unsupported model coverage names the missing model per leg", async () => {});
  test.fixme("stored correlation warnings render per kind", async () => {});
  test.fixme("workspace reloads from a saved analysis id in a new tab", async () => {});
});
