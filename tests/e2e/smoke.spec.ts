import { expect, test } from "@playwright/test";

test("web reaches API and database through the stack", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Auspex" })).toBeVisible();
  const status = page.getByRole("definition");
  await expect(status).toHaveText(["ok", "ok"]);
});
