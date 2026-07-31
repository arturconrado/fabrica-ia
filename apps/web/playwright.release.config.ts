import { defineConfig } from "@playwright/test";

import baseConfig from "./playwright.config";


export default defineConfig(baseConfig, {
  testMatch: "release.spec.ts",
  forbidOnly: true,
  metadata: {
    productionE2ERunId: process.env.ASF_PRODUCTION_E2E_RUN_ID || "",
  },
  reporter: [
    ["list"],
    ["json", { outputFile: process.env.ASF_PLAYWRIGHT_RELEASE_REPORT || "test-results/release.json" }],
  ],
});
