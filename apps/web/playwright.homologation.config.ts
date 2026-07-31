import { defineConfig, devices } from "@playwright/test";

const slowMo = Number(process.env.ASF_PLAYWRIGHT_SLOW_MO_MS || "1800");

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "homologation.interactive.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 90 * 60_000,
  expect: { timeout: 120_000 },
  outputDir: "test-results/homologation-visible",
  reporter: [
    ["list"],
    ["json", { outputFile: process.env.ASF_HOMOLOGATION_REPORT || "test-results/homologation-visible.json" }],
    ["html", { outputFolder: "playwright-report/homologation-visible", open: "never" }],
  ],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    viewport: { width: 1440, height: 960 },
    launchOptions: { slowMo: Number.isFinite(slowMo) ? slowMo : 1800 },
    screenshot: "only-on-failure",
    // The spec authenticates in temporary unrecorded contexts, then starts
    // recording from the resulting storage state.
    video: "off",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium-visible", use: { browserName: "chromium" } }],
});
