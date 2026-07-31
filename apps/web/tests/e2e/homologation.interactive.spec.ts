import { expect, test, type Browser, type Page, type Response, type TestInfo } from "@playwright/test";

const ENGAGEMENT_NAME = "Piloto real — Opportunity-to-Proposal Copilot";
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const SYNTHETIC_COMMENT = "SIMULAÇÃO DE HOMOLOGAÇÃO — identidade engagement_manager sintética, sem validade comercial ou aceite de produção.";
const STEP_WAIT_MS = 10 * 60_000;
const STATE_WAIT_MS = 15 * 60_000;
const COMMAND_WAIT_MS = 15 * 60_000;

type Execution = {
  id: string;
  engagement_id: string;
  work_item_id: string;
  execution_mode: "agent" | "technical_run" | "human" | "integration";
  status: string;
  last_error?: string;
};

type WorkItem = {
  id: string;
  engagement_id: string;
  title: string;
  execution_mode: Execution["execution_mode"];
  execution_id?: string | null;
  execution_status?: string | null;
  status: string;
};

type Deliverable = {
  id: string;
  title: string;
  status: string;
  current_revision: number;
  record_version: number;
  run_id: string | null;
  latest_revision?: { id: string; artifact_refs_json: string[]; evidence_refs_json: string[] } | null;
};

type AcceptanceCheck = {
  id: string;
  description: string;
  status: string;
  check_key: string;
  record_version: number;
};

type EngagementSnapshot = {
  id: string;
  status: string;
  record_version: number;
  plans: Array<{ version: number; status: string }>;
  work_items: WorkItem[];
  service_executions: Execution[];
  deliverables: Deliverable[];
  acceptance_checks: AcceptanceCheck[];
};

type ReviewItem = {
  id: string;
  kind: "run" | "service";
  title: string;
  status: string;
  run_id?: string | null;
};

type ReviewInbox = { items: ReviewItem[] };
type TechnicalRun = { id: string; status: string; homologation_readiness_score: number };

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for the visible homologation`);
  return value;
}

async function apiGet<T>(page: Page, path: string): Promise<T> {
  const response = await page.context().request.get(`${BASE_URL}/api-proxy${path}`);
  if (!response.ok()) throw new Error(`GET ${path} failed: HTTP ${response.status()}`);
  return response.json() as Promise<T>;
}

async function engagementSnapshot(page: Page, engagementId: string): Promise<EngagementSnapshot> {
  return apiGet<EngagementSnapshot>(page, `/api/v1/engagements/${engagementId}`);
}

function successfulCommand(response: Response, endpoint: string) {
  return response.request().method() === "POST" && response.url().includes(endpoint) && response.ok();
}

async function markDecisionCommandsSynthetic(page: Page) {
  await page.route("**/api-proxy/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isDecision = request.method() === "POST" && [
      /\/engagements\/[^/]+\/plans\/\d+\/approve$/,
      /\/review\/items\/[^/]+\/decisions$/,
      /\/service-deliverables\/[^/]+\/decisions$/,
      /\/service-deliverables\/[^/]+\/deliver$/,
      /\/acceptance-checks\/[^/]+\/decision$/,
    ].some((pattern) => pattern.test(url.pathname));
    if (!isDecision) {
      await route.continue();
      return;
    }
    const payload = request.postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({ ...payload, validation_mode: "synthetic" }),
      headers: { ...request.headers(), "content-type": "application/json" },
    });
  });
}

async function guide(
  page: Page,
  title: string,
  detail: string,
  tone: "blue" | "green" | "amber" = "blue",
  pause = false,
) {
  const stepMode = pause && process.env.ASF_PLAYWRIGHT_STEP_MODE === "1";
  const autoAdvanceMs = Number(process.env.ASF_PLAYWRIGHT_AUTO_ADVANCE_MS || "8000");
  await page.evaluate(({ title, detail, tone, stepMode, autoAdvanceMs }) => {
    const colors = {
      blue: ["#0f2a4a", "#38bdf8"],
      green: ["#102f26", "#34d399"],
      amber: ["#3a2810", "#fbbf24"],
    } as const;
    document.querySelector("#asf-playwright-guide")?.remove();
    const panel = document.createElement("section");
    panel.id = "asf-playwright-guide";
    panel.setAttribute("role", "status");
    panel.style.cssText = [
      "position:fixed", "z-index:2147483647", "top:18px", "left:50%", "transform:translateX(-50%)",
      "width:min(820px,calc(100vw - 32px))", `background:${colors[tone][0]}`,
      `border:2px solid ${colors[tone][1]}`, "border-radius:14px", "padding:16px 20px",
      "box-shadow:0 20px 60px rgba(0,0,0,.55)", "color:#f8fafc", "font-family:system-ui,sans-serif",
    ].join(";");
    const heading = document.createElement("strong");
    heading.textContent = `Playwright · ${title}`;
    heading.style.cssText = `display:block;color:${colors[tone][1]};font-size:16px;margin-bottom:6px`;
    const description = document.createElement("div");
    description.textContent = detail;
    description.style.cssText = "font-size:14px;line-height:1.5";
    panel.append(heading, description);
    if (stepMode) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Continuar demonstração";
      button.style.cssText = [
        "display:block", "width:100%", "margin-top:14px", "min-height:44px", "border:0", "border-radius:9px",
        `background:${colors[tone][1]}`, "color:#07111f", "font-weight:700", "cursor:pointer",
      ].join(";");
      button.addEventListener("click", () => {
        button.dataset.advanced = "true";
        button.textContent = "Avançando…";
        button.disabled = true;
      });
      panel.append(button);
      if (Number.isFinite(autoAdvanceMs) && autoAdvanceMs > 0) {
        const startedAt = Date.now();
        const countdown = window.setInterval(() => {
          const remaining = Math.max(0, Math.ceil((autoAdvanceMs - (Date.now() - startedAt)) / 1000));
          if (button.dataset.advanced === "true") {
            window.clearInterval(countdown);
            return;
          }
          button.textContent = `Continuar demonstração · ${remaining}s`;
        }, 250);
        window.setTimeout(() => button.click(), autoAdvanceMs);
      }
    }
    document.body.append(panel);
  }, { title, detail, tone, stepMode, autoAdvanceMs });
  if (stepMode) {
    await page.bringToFront();
    const continueButton = page.locator("#asf-playwright-guide button");
    await expect(continueButton).toBeVisible();
    await expect.poll(() => continueButton.getAttribute("data-advanced"), { timeout: STEP_WAIT_MS }).toBe("true");
    await page.evaluate(() => document.querySelector("#asf-playwright-guide")?.remove());
  }
}

async function login(page: Page, user: string, password: string, returnTo: string, expectedHeading: string) {
  await page.goto(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`, { waitUntil: "commit" });
  await page.locator("#username").fill(user);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL((url) => url.origin === new URL(BASE_URL).origin && url.pathname === returnTo);
  await expect(page.getByRole("heading", { name: expectedHeading, exact: true }).first()).toBeVisible();
}

async function authenticatedRecordedContext(
  browser: Browser,
  testInfo: TestInfo,
  label: "owner" | "vp",
  user: string,
  password: string,
  expectedHeading: string,
) {
  const authenticationContext = await browser.newContext({ baseURL: BASE_URL });
  const authenticationPage = await authenticationContext.newPage();
  await login(authenticationPage, user, password, "/dashboard", expectedHeading);
  const storageState = await authenticationContext.storageState();
  await authenticationContext.close();
  const context = await browser.newContext({
    baseURL: BASE_URL,
    storageState,
    viewport: { width: 1440, height: 960 },
    recordVideo: { dir: testInfo.outputPath(`${label}-video`), size: { width: 1440, height: 960 } },
  });
  const page = await context.newPage();
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: expectedHeading, exact: true }).first()).toBeVisible();
  testInfo.attach(`${label}-session-policy`, {
    body: Buffer.from("Authentication completed in an unrecorded context; isolated recording starts after login."),
    contentType: "text/plain",
  });
  return { context, page };
}

async function waitForRealTechnicalDecision(vpPage: Page, item: ReviewItem) {
  await vpPage.bringToFront();
  await vpPage.goto(`/approvals?item=${item.id}`);
  await expect(vpPage.getByRole("heading", { name: item.title, exact: true })).toBeVisible();
  await guide(vpPage, "decisão real do VP", `${item.title}: revise gates, HRS e evidências; registre sua decisão na interface.`, "amber", true);
  await vpPage.getByPlaceholder("Contexto, restrições ou mudanças necessárias…").focus();
  await expect.poll(async () => {
    const inbox = await apiGet<ReviewInbox>(vpPage, "/api/v1/review/inbox");
    return inbox.items.find((row) => row.id === item.id)?.status || "removed";
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).not.toBe("pending");
}

async function waitForRealManualEvidence(ownerPage: Page, engagementId: string, item: WorkItem) {
  await ownerPage.bringToFront();
  await ownerPage.goto("/work-queue");
  const row = ownerPage.locator("article").filter({ hasText: ENGAGEMENT_NAME }).filter({ hasText: item.title }).first();
  await expect(row).toBeVisible();
  await guide(ownerPage, "evidência real do owner", `${item.title}: registre a referência verificável e confirme a conclusão.`, "amber", true);
  await row.getByRole("textbox", { name: `Evidência para ${item.title}` }).focus();
  await expect.poll(async () => {
    const snapshot = await engagementSnapshot(ownerPage, engagementId);
    return snapshot.service_executions.find((execution) => execution.work_item_id === item.id)?.status;
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).not.toBe("waiting_for_evidence");
}

async function waitForRealDeliverableDecision(vpPage: Page, engagementId: string, deliverable: Deliverable, index: number) {
  await vpPage.bringToFront();
  await vpPage.goto(`/deliverables/${deliverable.id}`);
  await expect(vpPage.getByRole("heading", { name: deliverable.title, exact: true }).first()).toBeVisible();
  await guide(vpPage, `entregável real · ${index + 1}/13`, "Confira conteúdo, riscos e pacote editável; aprove e confirme a entrega pela interface.", "amber", true);
  const comment = vpPage.getByPlaceholder("Explique o aceite, os ajustes necessários ou o motivo da rejeição…");
  if (await comment.count()) await comment.focus();
  await expect.poll(async () => {
    const snapshot = await engagementSnapshot(vpPage, engagementId);
    return snapshot.deliverables.find((row) => row.id === deliverable.id)?.status;
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).toBe("delivered");
}

async function waitForRealCheckEvidence(ownerPage: Page, engagementId: string, check: AcceptanceCheck) {
  await ownerPage.bringToFront();
  await ownerPage.goto(`/engagements/${engagementId}`);
  const row = ownerPage.locator("article").filter({ hasText: check.description }).first();
  await expect(row).toBeVisible();
  await guide(ownerPage, "evidência real do DoD", check.description, "amber", true);
  await row.getByPlaceholder("artifact:…, relatório:…, ata:…").focus();
  await expect.poll(async () => {
    const snapshot = await engagementSnapshot(ownerPage, engagementId);
    return snapshot.acceptance_checks.find((item) => item.id === check.id)?.status;
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).not.toBe("pending");
}

async function waitForRealCheckDecision(vpPage: Page, engagementId: string, check: AcceptanceCheck) {
  await vpPage.bringToFront();
  await vpPage.goto(`/engagements/${engagementId}`);
  const row = vpPage.locator("article").filter({ hasText: check.description }).first();
  await expect(row).toBeVisible();
  await guide(vpPage, "decisão real do DoD", check.description, "amber", true);
  await row.getByPlaceholder("Explique a decisão e as condições do aceite…").focus();
  await expect.poll(async () => {
    const snapshot = await engagementSnapshot(vpPage, engagementId);
    return snapshot.acceptance_checks.find((item) => item.id === check.id)?.status;
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).toBe("passed");
}

async function waitForStateChange(ownerPage: Page, vpPage: Page, engagementId: string, previous: string) {
  await expect.poll(async () => {
    const state = await engagementSnapshot(ownerPage, engagementId);
    const inbox = await apiGet<ReviewInbox>(vpPage, "/api/v1/review/inbox");
    return JSON.stringify({
      executions: state.service_executions.map((row) => [row.id, row.status]),
      reviews: inbox.items.filter((row) => row.status === "pending").map((row) => row.id),
    });
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).not.toBe(previous);
}

async function completeSyntheticManualEvidence(ownerPage: Page, engagementId: string, item: WorkItem) {
  await ownerPage.bringToFront();
  await ownerPage.goto("/work-queue");
  await expect(ownerPage.getByRole("heading", { name: "Fila e capacidade" })).toBeVisible();
  const row = ownerPage.locator("article").filter({ hasText: ENGAGEMENT_NAME }).filter({ hasText: item.title }).first();
  await expect(row).toBeVisible();
  await guide(
    ownerPage,
    `evidência sintética · ${item.execution_mode}`,
    `${item.title}: a simulação registra uma referência explicitamente sintética; isso prova a esteira, não a realização perante cliente.`,
    "amber",
    true,
  );
  await row.getByRole("textbox", { name: `Evidência para ${item.title}` }).fill(`synthetic://playwright/${engagementId}/${item.id}`);
  const completed = ownerPage.waitForResponse((response) => successfulCommand(response, `/service-work-items/${item.id}/transitions`));
  await row.getByRole("button", { name: "Registrar conclusão" }).click();
  await completed;
}

async function approveTechnicalRun(vpPage: Page, item: ReviewItem) {
  await vpPage.bringToFront();
  await vpPage.goto(`/approvals?item=${item.id}`);
  await expect(vpPage.getByRole("heading", { name: "Aprovações" })).toBeVisible();
  await expect(vpPage.getByRole("heading", { name: item.title, exact: true })).toBeVisible();
  const approve = vpPage.getByRole("button", { name: "Aprovar", exact: true });
  await expect(approve).toBeEnabled();
  await guide(
    vpPage,
    "gate técnico da fábrica",
    `${item.title}: a identidade VP sintética confere os 17 gates, HRS e artifacts antes da aprovação de homologação.`,
    "green",
    true,
  );
  await vpPage.getByPlaceholder("Contexto, restrições ou mudanças necessárias…").fill(SYNTHETIC_COMMENT);
  const decided = vpPage.waitForResponse((response) => successfulCommand(response, `/review/items/${item.id}/decisions`));
  await approve.click();
  await decided;
  await expect(vpPage.getByText("Decisão registrada no ledger.")).toBeVisible();
}

async function produceAndSubmitDeliverable(ownerPage: Page, engagementId: string, deliverable: Deliverable) {
  await ownerPage.bringToFront();
  await ownerPage.goto(`/deliverables/${deliverable.id}`);
  await expect(ownerPage.getByRole("heading", { name: deliverable.title, exact: true }).first()).toBeVisible();
  let current = (await engagementSnapshot(ownerPage, engagementId)).deliverables.find((row) => row.id === deliverable.id)!;
  await guide(
    ownerPage,
    `produção do entregável ${current.current_revision ? `v${current.current_revision}` : "inicial"}`,
    `${deliverable.title}: conteúdo, critérios, evidências, riscos e próximos passos permanecem visíveis antes da submissão.`,
    "blue",
    true,
  );
  if (!current.current_revision) {
    await ownerPage.getByPlaceholder("Orientações específicas para esta revisão").fill(
      "Homologação sintética. Produza o entregável sem inventar entrevistas, integrações ou resultados; cite a evidência manual sintética e registre limitações.",
    );
    const generated = ownerPage.waitForResponse((response) => successfulCommand(response, `/service-deliverables/${deliverable.id}/revisions/generate`), { timeout: COMMAND_WAIT_MS });
    await ownerPage.getByRole("button", { name: "Gerar nova revisão" }).click();
    await generated;
    await expect(ownerPage.getByRole("heading", { name: "Submeter ao VP" })).toBeVisible();
    current = (await engagementSnapshot(ownerPage, engagementId)).deliverables.find((row) => row.id === deliverable.id)!;
  }
  if (current.status === "in_progress") {
    await ownerPage.getByPlaceholder("Resumo para decisão do VP").fill(
      "Revisão sintética produzida e conferida pelo owner para testar o fluxo completo; evidências e limitações estão explícitas.",
    );
    const submitted = ownerPage.waitForResponse((response) => successfulCommand(response, `/service-deliverables/${deliverable.id}/submit`));
    await ownerPage.getByRole("button", { name: "Submeter ao VP" }).click();
    await submitted;
    await expect(ownerPage.getByRole("heading", { name: "Aguardando validação do VP" })).toBeVisible();
  }
}

async function requestAndProduceCorrectedRevision(
  ownerPage: Page,
  vpPage: Page,
  engagementId: string,
  deliverable: Deliverable,
) {
  const before = (await engagementSnapshot(vpPage, engagementId)).deliverables.find(
    (row) => row.id === deliverable.id,
  );
  if (!before || before.status !== "review_ready") return;

  await vpPage.bringToFront();
  await vpPage.goto(`/deliverables/${deliverable.id}`);
  await expect(vpPage.getByRole("heading", { name: deliverable.title, exact: true }).first()).toBeVisible();
  await guide(
    vpPage,
    "ciclo realista de retrabalho",
    "O VP não aprova a primeira versão: solicita separação explícita entre fatos medidos, declarações do sponsor e hipóteses.",
    "amber",
    true,
  );
  await vpPage.getByPlaceholder("Explique o aceite, os ajustes necessários ou o motivo da rejeição…").fill(
    `${SYNTHETIC_COMMENT} Separe fatos medidos, declarações do sponsor e hipóteses; preserve as limitações na recomendação.`,
  );
  const requested = vpPage.waitForResponse((response) =>
    successfulCommand(response, `/service-deliverables/${deliverable.id}/decisions`),
  );
  await vpPage.getByRole("button", { name: "Solicitar ajustes" }).click();
  await requested;

  await ownerPage.bringToFront();
  await ownerPage.goto(`/deliverables/${deliverable.id}`);
  await expect(ownerPage.getByRole("button", { name: "Gerar nova revisão" })).toBeVisible();
  await ownerPage.getByPlaceholder("Orientações específicas para esta revisão").fill(
    "Produza a correção solicitada pelo VP. Separe fatos medidos, declarações e hipóteses; mantenha evidências, riscos e próximos passos verificáveis.",
  );
  const generated = ownerPage.waitForResponse((response) =>
    successfulCommand(response, `/service-deliverables/${deliverable.id}/revisions/generate`),
    { timeout: COMMAND_WAIT_MS },
  );
  await ownerPage.getByRole("button", { name: "Gerar nova revisão" }).click();
  await generated;
  await ownerPage.getByPlaceholder("Resumo para decisão do VP").fill(
    "Revisão corrigida após comentário do VP; proveniência e limitações foram explicitadas.",
  );
  const submitted = ownerPage.waitForResponse((response) =>
    successfulCommand(response, `/service-deliverables/${deliverable.id}/submit`),
  );
  await ownerPage.getByRole("button", { name: "Submeter ao VP" }).click();
  await submitted;

  const after = (await engagementSnapshot(ownerPage, engagementId)).deliverables.find(
    (row) => row.id === deliverable.id,
  );
  expect(after?.status).toBe("review_ready");
  expect(after?.current_revision).toBe(before.current_revision + 1);
}

async function waitForRealDeliverableSubmission(ownerPage: Page, engagementId: string, deliverable: Deliverable, index: number) {
  await ownerPage.bringToFront();
  await ownerPage.goto(`/deliverables/${deliverable.id}`);
  await expect(ownerPage.getByRole("heading", { name: deliverable.title, exact: true }).first()).toBeVisible();
  await guide(
    ownerPage,
    `submissão real do owner · ${index + 1}/13`,
    "Gere ou confira a revisão, aplique o rascunho somente se adequado e submeta explicitamente ao VP.",
    "amber",
    true,
  );
  const instructions = ownerPage.getByPlaceholder("Orientações específicas para esta revisão");
  if (await instructions.count()) await instructions.focus();
  await expect.poll(async () => {
    const snapshot = await engagementSnapshot(ownerPage, engagementId);
    return snapshot.deliverables.find((row) => row.id === deliverable.id)?.status;
  }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).toBe("review_ready");
}

async function approveDownloadAndDeliver(vpPage: Page, engagementId: string, deliverable: Deliverable, index: number, testInfo: TestInfo) {
  await vpPage.bringToFront();
  await vpPage.goto(`/deliverables/${deliverable.id}`);
  await expect(vpPage.getByRole("heading", { name: deliverable.title, exact: true }).first()).toBeVisible();
  let current = (await engagementSnapshot(vpPage, engagementId)).deliverables.find((row) => row.id === deliverable.id)!;
  if (current.status === "review_ready") {
    await guide(
      vpPage,
      `validação VP sintética · ${index + 1}/13`,
      `${deliverable.title}: o Playwright exibe conteúdo, critérios, evidências e riscos antes de registrar a decisão sintética.`,
      "green",
      true,
    );
    await vpPage.getByPlaceholder("Explique o aceite, os ajustes necessários ou o motivo da rejeição…").fill(SYNTHETIC_COMMENT);
    const approved = vpPage.waitForResponse((response) => successfulCommand(response, `/service-deliverables/${deliverable.id}/decisions`));
    await vpPage.getByRole("button", { name: "Aprovar entregável" }).click();
    await approved;
    await expect(vpPage.getByRole("heading", { name: "Confirmar entrega final" })).toBeVisible();
    current = (await engagementSnapshot(vpPage, engagementId)).deliverables.find((row) => row.id === deliverable.id)!;
  }
  if (current.status === "approved") {
    const downloadPromise = vpPage.waitForEvent("download");
    await vpPage.getByRole("link", { name: "Pacote editável" }).click();
    const download = await downloadPromise;
    const packagePath = testInfo.outputPath(`package-${String(index + 1).padStart(2, "0")}.zip`);
    await download.saveAs(packagePath);
    await testInfo.attach(`package-${index + 1}`, { path: packagePath, contentType: "application/zip" });
    await vpPage.getByPlaceholder("Ex.: pacote apresentado ao comitê e aceite registrado na ata…").fill(
      `${SYNTHETIC_COMMENT} Pacote baixado e checksum preservado na evidência Playwright.`,
    );
    const delivered = vpPage.waitForResponse((response) => successfulCommand(response, `/service-deliverables/${deliverable.id}/deliver`));
    await vpPage.getByRole("button", { name: "Confirmar entrega final" }).click();
    await delivered;
    await expect(vpPage.getByRole("heading", { name: "Entrega concluída" })).toBeVisible();
  }
  if (current.status === "synthetic_approved") {
    await vpPage.getByPlaceholder("Ex.: pacote apresentado ao comitê e aceite registrado na ata…").fill(
      `${SYNTHETIC_COMMENT} Nenhum pacote comercial é liberado por uma decisão sintética.`,
    );
    const delivered = vpPage.waitForResponse((response) => successfulCommand(response, `/service-deliverables/${deliverable.id}/deliver`));
    await vpPage.getByRole("button", { name: "Confirmar entrega final" }).click();
    await delivered;
    await expect(vpPage.getByRole("heading", { name: "Entrega concluída" })).toBeVisible();
  }
}

async function recordCheckEvidence(ownerPage: Page, engagementId: string, check: AcceptanceCheck, deliveredIds: string[]) {
  await ownerPage.bringToFront();
  await ownerPage.goto(`/engagements/${engagementId}`);
  const row = ownerPage.locator("article").filter({ hasText: check.description }).first();
  await expect(row).toBeVisible();
  const refs = [`synthetic://playwright/${engagementId}/check/${check.check_key}`, ...deliveredIds.slice(0, 3).map((id) => `deliverable:${id}`)];
  await row.getByPlaceholder("artifact:…, relatório:…, ata:…").fill(refs.join(", "));
  const recorded = ownerPage.waitForResponse((response) => successfulCommand(response, `/acceptance-checks/${check.id}/evidence`));
  await row.getByRole("button", { name: "Registrar evidência para o VP" }).click();
  await recorded;
}

async function decideCheck(vpPage: Page, engagementId: string, check: AcceptanceCheck) {
  await vpPage.bringToFront();
  await vpPage.goto(`/engagements/${engagementId}`);
  const row = vpPage.locator("article").filter({ hasText: check.description }).first();
  await expect(row).toBeVisible();
  await row.getByPlaceholder("Explique a decisão e as condições do aceite…").fill(SYNTHETIC_COMMENT);
  const decided = vpPage.waitForResponse((response) => successfulCommand(response, `/acceptance-checks/${check.id}/decision`));
  await row.getByRole("button", { name: "Aprovar check" }).click();
  await decided;
}

test("visible end-to-end homologation exercises the complete service operation", async ({ browser }, testInfo) => {
  test.skip(process.env.ASF_INTERACTIVE_HOMOLOGATION !== "1", "Set ASF_INTERACTIVE_HOMOLOGATION=1 to open the visible journey");

  const engagementId = requiredEnv("ASF_TEST_SERVICE_ENGAGEMENT_ID");
  const ownerUser = process.env.ASF_TEST_OIDC_USER?.trim() || "operator@local.dev";
  const ownerPassword = process.env.ASF_TEST_OIDC_PASSWORD?.trim() || "ChangeMe123!";
  const vpUser = requiredEnv("ASF_TEST_VP_OIDC_USER");
  const vpPassword = requiredEnv("ASF_TEST_VP_OIDC_PASSWORD");
  const simulateVp = process.env.ASF_SIMULATE_VP === "1";
  const technicalRunIds = [
    requiredEnv("ASF_TEST_CONTRACTFLOW_RUN_ID"),
    requiredEnv("ASF_TEST_SERVICEDESK_RUN_ID"),
  ];
  const engagementPath = `/engagements/${engagementId}`;

  const ownerSession = await authenticatedRecordedContext(browser, testInfo, "owner", ownerUser, ownerPassword, "Hoje");
  const vpSession = await authenticatedRecordedContext(browser, testInfo, "vp", vpUser, vpPassword, "Minha fila");
  const { context: ownerContext, page } = ownerSession;
  const { context: vpContext, page: vpPage } = vpSession;

  try {
    await test.step("autenticar owner e VP em contextos isolados", async () => {
      await guide(page, "owner autenticado", "Página Hoje, sessão HttpOnly e tenant ativo. Clique para percorrer cada detalhe.", "blue", true);
      await page.goto("/service-catalog");
      await expect(page.getByRole("heading", { name: "AI Use Case Pilot", exact: true })).toBeVisible();
      await guide(page, "catálogo 2.0", "A oferta contratada preserva processo, 13 entregáveis, responsáveis, formatos e Definition of Done.", "blue", true);
      if (simulateVp) await markDecisionCommandsSynthetic(vpPage);
    });

    await test.step("VP decide as duas missões técnicas completas", async () => {
      for (const runId of technicalRunIds) {
        const run = await apiGet<TechnicalRun>(vpPage, `/runs/${runId}`);
        if (run.status === "approved_for_homologation") continue;
        expect(run.status).toBe("waiting_for_human");
        expect(run.homologation_readiness_score).toBeGreaterThanOrEqual(90);
        const inbox = await apiGet<ReviewInbox>(vpPage, "/api/v1/review/inbox");
        const review = inbox.items.find((item) => item.kind === "run" && item.run_id === runId && item.status === "pending");
        if (!review) throw new Error(`Pending VP review not found for technical run ${runId}`);
        if (simulateVp) await approveTechnicalRun(vpPage, review);
        else await waitForRealTechnicalDecision(vpPage, review);
        await expect.poll(async () => {
          const current = await apiGet<TechnicalRun>(vpPage, `/runs/${runId}`);
          return current.status;
        }, { timeout: STATE_WAIT_MS, intervals: [3_000, 5_000, 10_000] }).toBe("approved_for_homologation");
      }
    });

    await page.goto(engagementPath);
    await expect(page.getByRole("heading", { name: ENGAGEMENT_NAME, exact: true })).toBeVisible();
    await expect(page.getByText("Esteira guiada", { exact: true })).toBeVisible();
    await guide(page, "caso comercial", "Opportunity-to-Proposal Copilot: contrato, plano provider-real, riscos, seis workstreams e 13 entregáveis.", "blue", true);

    let state = await engagementSnapshot(page, engagementId);
    const latestPlan = state.plans.at(-1);
    if (latestPlan?.status === "draft") {
      await vpPage.bringToFront();
      await vpPage.goto(engagementPath);
      await expect(vpPage.getByText("Visão do VP", { exact: true })).toBeVisible();
      const approve = vpPage.getByRole("button", { name: "Aprovar e liberar para o owner" });
      await expect(approve).toBeVisible();
      await guide(
        vpPage,
        simulateVp ? "simulação controlada da decisão do VP" : "decisão humana obrigatória",
        simulateVp ? "A decisão ficará marcada como sintética no comentário e serve apenas para provar o fluxo." : "O Playwright aguardará o VP real digitar o comentário e decidir.",
        "amber",
        true,
      );
      const approval = vpPage.waitForResponse((response) => successfulCommand(response, `/engagements/${engagementId}/plans/${latestPlan.version}/approve`), { timeout: COMMAND_WAIT_MS });
      if (simulateVp) {
        await vpPage.getByPlaceholder("Confirme escopo, riscos e condições para iniciar…").fill(SYNTHETIC_COMMENT);
        await approve.click();
      } else {
        await vpPage.getByPlaceholder("Confirme escopo, riscos e condições para iniciar…").focus();
      }
      await approval;
      await expect(approve).toHaveCount(0);
    }

    await page.bringToFront();
    await page.goto(engagementPath);
    state = await engagementSnapshot(page, engagementId);
    if (state.status !== "active") {
      await guide(page, "materialização", "O owner transforma o plano aprovado em workstreams, work items, entregáveis, equipe e checks persistidos.", "blue", true);
      const activated = page.waitForResponse((response) => successfulCommand(response, `/engagements/${engagementId}/activate`));
      await page.getByRole("button", { name: "Ativar e materializar a operação" }).click();
      await activated;
      await expect(page.getByRole("heading", { name: "Fila multi-serviço" })).toBeVisible();
    }

    await page.goto("/work-queue");
    await expect(page.getByRole("heading", { name: "Fila e capacidade" })).toBeVisible();
    await guide(page, "fila durável e WIP", "Os 13 itens serão enfileirados um a um; o dispatcher preserva WIP 5 global e 2 por tenant.", "blue", true);
    let allItemsQueued = false;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      state = await engagementSnapshot(page, engagementId);
      expect(state.work_items).toHaveLength(13);
      const queue = await apiGet<{ items: WorkItem[] }>(page, "/api/v1/operator/work-queue");
      const pending = queue.items.find((item) => item.engagement_id === engagementId && !item.execution_id);
      if (!pending) {
        allItemsQueued = true;
        break;
      }
      const row = page.locator("article").filter({ hasText: ENGAGEMENT_NAME }).filter({ hasText: pending.title }).first();
      await expect(row).toBeVisible();
      const enqueue = row.getByRole("button", { name: "Enfileirar" });
      await expect(enqueue).toBeVisible();
      const queued = page.waitForResponse((response) => successfulCommand(response, "/service-work-items/") && response.url().endsWith("/execute"));
      await enqueue.scrollIntoViewIfNeeded();
      await enqueue.click();
      const queuedResponse = await queued;
      const execution = await queuedResponse.json() as Execution;
      await expect.poll(async () => {
        const snapshot = await apiGet<{ items: WorkItem[] }>(page, "/api/v1/operator/work-queue");
        return snapshot.items.find((item) => item.id === execution.work_item_id)?.execution_id || null;
      }, { message: `A execução durável de ${pending.title} deve aparecer antes do próximo comando` }).toBe(execution.id);
      await expect(row.getByRole("button", { name: "Enfileirar" })).toHaveCount(0);
    }
    expect(allItemsQueued, "all 13 work items must enter the durable queue within the bounded loop").toBe(true);

    await guide(page, "execução provider-real", "Cinco entregáveis agent, seis fábricas técnicas completas e duas atividades com evidência sintética controlada.", "blue", true);
    let allExecutionsReady = false;
    for (let transition = 0; transition < 180; transition += 1) {
      state = await engagementSnapshot(page, engagementId);
      const failures = state.service_executions.filter((row) => ["failed", "cancelled"].includes(row.status));
      if (failures.length) throw new Error(`Service executions failed: ${failures.map((row) => `${row.id}:${row.last_error || row.status}`).join(" | ")}`);
      const runIds = new Set(state.deliverables.map((row) => row.run_id).filter(Boolean));
      const inbox = await apiGet<ReviewInbox>(vpPage, "/api/v1/review/inbox");
      const technicalReview = inbox.items.find((row) => row.kind === "run" && row.status === "pending" && row.run_id && runIds.has(row.run_id));
      if (technicalReview) {
        if (simulateVp) await approveTechnicalRun(vpPage, technicalReview);
        else await waitForRealTechnicalDecision(vpPage, technicalReview);
        continue;
      }
      const waitingEvidence = state.service_executions.find((row) => row.status === "waiting_for_evidence");
      if (waitingEvidence) {
        const item = state.work_items.find((row) => row.id === waitingEvidence.work_item_id);
        if (!item) throw new Error(`Missing work item ${waitingEvidence.work_item_id}`);
        if (simulateVp) await completeSyntheticManualEvidence(page, engagementId, item);
        else await waitForRealManualEvidence(page, engagementId, item);
        continue;
      }
      if (state.service_executions.length === 13 && state.service_executions.every((row) => row.status === "awaiting_review")) {
        allExecutionsReady = true;
        break;
      }
      const signature = JSON.stringify({
        executions: state.service_executions.map((row) => [row.id, row.status]),
        reviews: inbox.items.filter((row) => row.status === "pending").map((row) => row.id),
      });
      await page.bringToFront();
      await page.goto(engagementPath);
      await guide(page, "produção em curso", `${state.service_executions.filter((row) => row.status === "awaiting_review").length}/13 itens prontos; a tela acompanha checkpoints reais do Temporal.`, "blue");
      await waitForStateChange(page, vpPage, engagementId, signature);
    }
    expect(allExecutionsReady, "all 13 executions must reach review within the bounded homologation").toBe(true);

    state = await engagementSnapshot(page, engagementId);
    await guide(page, "13 execuções concluídas", "Todos os work items chegaram a revisão sem slot órfão ou retry infinito. Agora o owner prepara a submissão executiva.", "green", true);
    for (const [index, deliverable] of state.deliverables.entries()) {
      if (simulateVp) await produceAndSubmitDeliverable(page, engagementId, deliverable);
      else await waitForRealDeliverableSubmission(page, engagementId, deliverable, index);
    }

    state = await engagementSnapshot(page, engagementId);
    expect(state.deliverables).toHaveLength(13);
    expect(state.deliverables.every((row) => row.status === "review_ready")).toBe(true);
    if (simulateVp) {
      await requestAndProduceCorrectedRevision(page, vpPage, engagementId, state.deliverables[0]);
      state = await engagementSnapshot(page, engagementId);
      expect(state.deliverables[0].current_revision).toBeGreaterThan(1);
      expect(state.deliverables[0].status).toBe("review_ready");
    }
    for (const [index, deliverable] of state.deliverables.entries()) {
      if (simulateVp) await approveDownloadAndDeliver(vpPage, engagementId, deliverable, index, testInfo);
      else await waitForRealDeliverableDecision(vpPage, engagementId, deliverable, index);
    }

    state = await engagementSnapshot(page, engagementId);
    const deliveredStatus = simulateVp ? "synthetic_delivered" : "delivered";
    const passedStatus = simulateVp ? "synthetic_passed" : "passed";
    const deliveredIds = state.deliverables.filter((row) => row.status === deliveredStatus).map((row) => row.id);
    expect(deliveredIds).toHaveLength(13);
    await guide(page, "Definition of Done", `O owner registra evidências ${simulateVp ? "sintéticas" : "reais"} nos ${state.acceptance_checks.length} checks; depois a identidade VP separada decide.`, "amber", true);
    for (const check of state.acceptance_checks.filter((row) => row.status === "pending")) {
      if (simulateVp) await recordCheckEvidence(page, engagementId, check, deliveredIds);
      else await waitForRealCheckEvidence(page, engagementId, check);
    }
    state = await engagementSnapshot(page, engagementId);
    for (const check of state.acceptance_checks.filter((row) => row.status === "evidence_recorded")) {
      if (simulateVp) await decideCheck(vpPage, engagementId, check);
      else await waitForRealCheckDecision(vpPage, engagementId, check);
    }

    const finalState = await engagementSnapshot(page, engagementId);
    expect(finalState.status).toBe("active");
    expect(finalState.service_executions).toHaveLength(13);
    expect(finalState.service_executions.every((row) => row.status === "awaiting_review")).toBe(true);
    expect(finalState.deliverables.every((row) => row.status === deliveredStatus)).toBe(true);
    expect(finalState.acceptance_checks.every((row) => row.status === passedStatus)).toBe(true);
    await vpPage.bringToFront();
    await vpPage.goto(engagementPath);
    await guide(
      vpPage,
      simulateVp ? "homologação sintética concluída" : "homologação humana concluída",
      simulateVp
        ? "O caso percorreu a esteira, mas decisões sintéticas não liberam produção."
        : "Owner e VP concluíram catálogo, plano, WIP, Temporal, artifacts, pacotes, four-eyes e DoD com decisões reais.",
      "green",
      true,
    );
    await testInfo.attach("final-engagement-state", {
      body: Buffer.from(JSON.stringify(finalState, null, 2)),
      contentType: "application/json",
    });
  } finally {
    await ownerContext.close();
    await vpContext.close();
  }
});
