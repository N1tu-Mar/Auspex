import { defineConfig, devices } from "@playwright/test";

// Smoke tests run against an already-running stack (`docker compose up --build`).
export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
