import { expect, test } from "@playwright/test";

test("enterprise run can be started, inspected, approved and fed back from the UI", async ({ page }) => {
  test.skip(!process.env.ASF_TEST_BEARER_TOKEN, "ASF_TEST_BEARER_TOKEN is required for production-only E2E");
  test.setTimeout(120_000);
  await page.addInitScript((token) => {
    window.localStorage.setItem("asf_bearer_token", String(token));
  }, process.env.ASF_TEST_BEARER_TOKEN);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Build enterprise software with governed agent teams." })).toBeVisible();

  await page.getByRole("button", { name: /Start Enterprise Build/i }).click();
  await page.waitForURL(/\/runs\/[0-9a-f-]+/);

  await expect(page.getByRole("heading", { name: "Build Chat" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Agent Activity" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Preview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quality Rail" })).toBeVisible();
  await expect(page.getByText("Demand Classifier").first()).toBeVisible();
  await expect(page.getByText("Quality Governor").first()).toBeVisible();

  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Resume", exact: true }).click();

  await expect(page.getByText("Human approval is waiting for a release decision.")).toBeVisible({ timeout: 90_000 });

  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Workflow Graph" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("approval.requested")).toBeVisible();
  await expect(page.getByText("artifact.created").first()).toBeVisible();
  await expect(page.getByText("93.45").first()).toBeVisible();

  await page.getByRole("button", { name: "Quality", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Homologation Readiness" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quality Gates" })).toBeVisible();
  await expect(page.getByText("REQ-001").first()).toBeVisible();
  await expect(page.getByText("REQ-010").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Traceability Matrix" })).toBeVisible();

  await page.getByRole("button", { name: "Files", exact: true }).click();
  await expect(page.getByText("generated_app/app/services.py").first()).toBeVisible();
  await expect(page.getByText("Diffs")).toBeVisible();
  await expect(page.getByText("HOMOLOGATION_REPORT.md")).toBeVisible();

  await page.getByRole("button", { name: "Tests", exact: true }).click();
  await expect(page.getByText("python -m pytest generated_app/tests").first()).toBeVisible();
  await expect(page.getByText("Passed 8 · Failed 0").first()).toBeVisible();

  await page.getByRole("button", { name: "Approval", exact: true }).click();
  await expect(page.getByText("Aprovação final de homologação")).toBeVisible();
  await page.getByPlaceholder("Human comment").fill("Release validation approved from Playwright.");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("approved_for_homologation").first()).toBeVisible();

  await page.getByRole("button", { name: "Quality", exact: true }).click();
  await page.getByPlaceholder("Feedback comment").fill("UI release validation evidence is clear.");
  await page.getByRole("button", { name: "Positive" }).click();
  await expect(page.getByText("UI release validation evidence is clear.")).toBeVisible();
});
