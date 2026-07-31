import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";


async function login(page: Page) {
  await page.goto("/auth/login?returnTo=%2Fdashboard", { waitUntil: "commit" });
  await page.locator("#username").fill(process.env.ASF_TEST_OIDC_USER || "operator@local.dev");
  await page.locator("#password").fill(process.env.ASF_TEST_OIDC_PASSWORD || "ChangeMe123!");
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL((url) => url.origin === "http://localhost:3000" && url.pathname === "/dashboard");
  await expect(page.locator("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
}

async function loginAs(page: Page, user: string, password: string, heading: string) {
  await page.goto("/auth/login?returnTo=%2Fdashboard", { waitUntil: "commit" });
  await page.locator("#username").fill(user);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL((url) => url.origin === "http://localhost:3000" && url.pathname === "/dashboard");
  await expect(page.getByRole("heading", { name: heading })).toBeVisible();
}


test("OIDC PKCE keeps tokens HttpOnly and refreshes the BFF session", async ({ page, context, browser }) => {
  const protectedFailures: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api-proxy/") && response.status() === 401) protectedFailures.push(response.status());
  });

  await login(page);
  const cookies = await context.cookies();
  const access = cookies.find((cookie) => cookie.name === "asf_access_token");
  const refresh = cookies.find((cookie) => cookie.name === "asf_refresh_token");
  expect(access).toBeDefined();
  expect(refresh).toBeDefined();
  if (!access || !refresh) throw new Error("OIDC callback did not create the token cookies");
  expect(access.httpOnly).toBe(true);
  expect(refresh.httpOnly).toBe(true);
  expect(access.sameSite).toBe("Lax");
  await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
  const storage = await page.evaluate(() => ({
    local: Object.keys(window.localStorage),
    session: Object.keys(window.sessionStorage),
    body: document.body.textContent || ""
  }));
  expect(storage.local.some((key) => /token|bearer/i.test(key))).toBe(false);
  expect(storage.session.some((key) => /token|bearer/i.test(key))).toBe(false);
  expect(storage.body).not.toContain(access.value);

  const refreshOnlyContext = await browser.newContext();
  await refreshOnlyContext.addCookies([refresh]);
  const refreshResponse = await refreshOnlyContext.request.get("http://localhost:3000/auth/session");
  expect(refreshResponse.status()).toBe(200);
  const refreshedAccess = (await refreshOnlyContext.cookies()).find((cookie) => cookie.name === "asf_access_token");
  expect(refreshedAccess?.httpOnly).toBe(true);
  expect((refreshedAccess?.value.length || 0) > 100).toBe(true);
  await refreshOnlyContext.close();
  expect(protectedFailures).toEqual([]);
});


test("session failure is explicit and retry recovers without a page reload", async ({ page }) => {
  await login(page);
  let attempts = 0;
  await page.route("**/auth/session", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "SESSION_UPSTREAM_UNAVAILABLE", correlation_id: "e2e-session-retry" } }),
      });
      return;
    }
    await route.continue();
  });
  await page.reload();
  await expect(page.getByText("Sessão indisponível", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tentar novamente" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Tentar novamente" }).first().click();
  await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
  expect(attempts).toBeGreaterThanOrEqual(2);
});


test("resource timeout becomes an explicit retryable state without infinite loading", async ({ page }) => {
  await login(page);
  let attempts = 0;
  await page.route("**/api-proxy/api/v1/operator/work-queue", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 504,
        contentType: "application/json",
        body: JSON.stringify({ detail: {
          code: "UPSTREAM_TIMEOUT", message: "A API não respondeu dentro do prazo.",
          correlation_id: "e2e-resource-timeout",
        } }),
      });
      return;
    }
    await route.continue();
  });
  const startedAt = Date.now();
  await page.goto("/work-queue");
  await expect(page.getByRole("alert").filter({ hasText: "UPSTREAM_TIMEOUT" })).toBeVisible();
  expect(Date.now() - startedAt, "the timeout must become explicit within 15 seconds").toBeLessThanOrEqual(15_000);
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(page.getByRole("heading", { name: "Fila e capacidade" })).toBeVisible();
  expect(attempts).toBeGreaterThanOrEqual(2);
});


test("operator routes render real empty states without authorization failures", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  const failures: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api-proxy/") && response.status() >= 400) failures.push(`${response.status()} ${response.url()}`);
  });
  for (const path of [
    "/mvp-factory",
    "/clients",
    "/service-catalog",
    "/engagements",
    "/work-queue",
    "/projects",
    "/programs",
    "/opportunities",
    "/components",
    "/mvp-runs",
    "/runs",
    "/batches",
    "/approvals",
    "/knowledge",
    "/evidence",
    "/deliverables",
    "/agents",
    "/ai-activity",
    "/runtime",
    "/connectors",
    "/learning",
    "/admin/contracts",
    "/admin/tenants"
  ]) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator('aside a[href="/auth/logout"]')).toBeVisible();
    await expect(page.locator("main h1, main h2").first()).toBeVisible();
    const body = await page.locator("body").innerText();
    // Match the retired UI fixtures precisely. Persisted client artifacts may
    // legitimately discuss demo/test data and must not be censored by this
    // platform-shell assertion.
    for (const forbidden of ["Aurora Health", "Atlas Industrial", "Nimbus Financeira", "Recent builds:", "Agents queued:", "Demo dataset loaded"]) {
      expect(body).not.toContain(forbidden);
    }
  }
  expect(failures).toEqual([]);
});


test("service portfolio exposes a readable end-to-end flow for every v2 offering", async ({ page }) => {
  await login(page);
  await page.goto("/service-catalog");
  await expect(page.getByRole("heading", { name: "Produtos e serviços" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Opere uma oferta, várias em paralelo ou uma sequência completa" })).toBeVisible();
  for (const principle of ["Autonomia por serviço", "Paralelismo controlado", "Dependência explícita"]) {
    await expect(page.getByText(principle, { exact: true })).toBeVisible();
  }
  for (const offering of [
    "AI Value Discovery",
    "AI Governance & Risk Framework",
    "AI Enterprise Launchpad",
    "AI Workforce Productivity Accelerator",
    "AI Engineering Productivity Accelerator",
    "AI Use Case Pilot",
    "AI Office as a Service",
    "AI Adoption Kit & Governance Cockpit",
  ]) {
    await expect(page.getByRole("heading", { name: offering }).first()).toBeVisible();
  }
  await expect(page.getByText("Operar continuamente", { exact: true }).first()).toBeVisible();
  const v2OfferingCards = page.locator("article.panel").filter({ has: page.getByRole("link", { name: "Ver fluxo completo" }) });
  await expect(v2OfferingCards).toHaveCount(8);
  await expect(page.getByText("Versões históricas preservadas", { exact: true })).toBeVisible();

  await v2OfferingCards.filter({ has: page.getByRole("heading", { name: "AI Value Discovery" }) }).getByRole("link", { name: "Ver fluxo completo" }).click();
  await expect(page.getByRole("heading", { name: "AI Value Discovery", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "O que acontece, passo a passo" })).toBeVisible();
  for (const stage of ["Alinhamento estratégico", "Diagnóstico de maturidade", "Mapeamento dos processos", "Identificação dos casos de uso", "Priorização", "Construção do roadmap"]) {
    await expect(page.getByRole("heading", { name: stage })).toBeVisible();
  }
  await expect(page.getByText("Entregáveis incluídos", { exact: true })).toBeVisible();
  await expect(page.getByText("Definition of Done da oferta", { exact: true })).toBeVisible();
  await expect(page.getByText("Definition of Done corporativo", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Iniciar este serviço" }).first()).toBeVisible();

  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("heading", { name: "AI Value Discovery", level: 1 })).toBeVisible();
    const layout = await page.evaluate(() => ({ viewport: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    expect(layout.scrollWidth, `offering detail overflowed at ${width}px`).toBeLessThanOrEqual(layout.viewport + 1);
  }
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});


test("release tenant proves contract, entitlement, component and audit isolation", async ({ page }) => {
  await login(page);
  const releaseTenantId = process.env.ASF_RELEASE_TENANT_ID || "release-homologation";
  const selected = await page.request.post("/auth/tenant", { data: { tenant_id: releaseTenantId } });
  expect(selected.status()).toBe(200);

  const session = await page.request.get("/auth/session");
  expect(session.status()).toBe(200);
  const sessionBody = await session.json() as { me: { tenant_id: string; role: string } };
  expect(sessionBody.me.tenant_id).toBe(releaseTenantId);
  expect(sessionBody.me.role).toBe("owner");

  const [programsResponse, contractsResponse, entitlementsResponse, componentsResponse, auditResponse] = await Promise.all([
    page.request.get("/api-proxy/programs"),
    page.request.get("/api-proxy/contracts"),
    page.request.get("/api-proxy/entitlements"),
    page.request.get("/api-proxy/component-instances"),
    page.request.get("/api-proxy/audit-events"),
  ]);
  for (const response of [programsResponse, contractsResponse, entitlementsResponse, componentsResponse, auditResponse]) {
    expect(response.status()).toBe(200);
  }
  const programs = await programsResponse.json() as Array<{ id: string; name: string }>;
  const contracts = await contractsResponse.json() as Array<{ contract_number: string; status: string }>;
  const entitlements = await entitlementsResponse.json() as Array<{ component_code: string; status: string }>;
  const components = await componentsResponse.json() as Array<{ component_code: string; project: { id: string } }>;
  const events = await auditResponse.json() as Array<{ event_type: string }>;
  expect(programs.some((item) => item.name === "Release Homologation 2.1")).toBe(true);
  expect(contracts.some((item) => item.contract_number === "ASF-RELEASE-HOMOLOGATION-2.1" && item.status === "active")).toBe(true);
  expect(entitlements).toEqual(expect.arrayContaining([
    expect.objectContaining({ component_code: "rapid_mvp_factory", status: "granted" }),
  ]));
  const contracted = components.find((item) => item.component_code === "rapid_mvp_factory");
  expect(contracted).toBeDefined();
  expect(events.some((item) => item.event_type === "release_component.seeded")).toBe(true);

  const denied = await page.request.post(`/api-proxy/projects/${contracted?.project.id}/components`, {
    data: { component_code: "ai_value_discovery", status: "ready" },
  });
  expect(denied.status()).toBe(403);
  const deniedBody = await denied.json() as { detail?: { code?: string } };
  expect(deniedBody.detail?.code).toBe("ENTITLEMENT_REQUIRED");
  const after = await page.request.get("/api-proxy/component-instances");
  expect((await after.json() as unknown[]).length).toBe(components.length);
});


test("engagement board keeps autonomous services readable across the full journey", async ({ page }) => {
  await login(page);
  await page.goto("/engagements");
  await expect(page.getByRole("heading", { name: "Engajamentos" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Portfólio em operação" })).toBeVisible();
  for (const phase of ["1. Plano", "2. Aprovação", "3. Execução", "4. Entregáveis", "5. Aceite e entrega"]) {
    await expect(page.getByRole("heading", { name: phase })).toBeVisible();
  }
  await expect(page.getByText("Cada cartão é uma trilha autônoma.", { exact: false })).toBeVisible();
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("heading", { name: "Portfólio em operação" })).toBeVisible();
    const layout = await page.evaluate(() => ({ viewport: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    expect(layout.scrollWidth, `engagement board overflowed at ${width}px`).toBeLessThanOrEqual(layout.viewport + 1);
  }
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});


test("dashboard is keyboard accessible, responsive and axe-clean", async ({ page }) => {
  await login(page);
  await page.keyboard.press("Home");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#conteudo-principal")).toBeFocused();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
    const layout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      desktopMedia: window.matchMedia("(min-width: 1024px)").matches,
      shellPadding: getComputedStyle(document.querySelector("body > div > div") || document.body).paddingLeft,
      offenders: Array.from(document.querySelectorAll<HTMLElement>("body *"))
        .map((element) => ({ element, rect: element.getBoundingClientRect() }))
        .filter(({ rect }) => rect.right > window.innerWidth + 1 && rect.left < window.innerWidth)
        .sort((left, right) => right.rect.right - left.rect.right)
        .slice(0, 8)
        .map(({ element, rect }) => `${element.tagName.toLowerCase()}.${element.className}[${Math.round(rect.left)}..${Math.round(rect.right)}]`)
    }));
    expect(layout.scrollWidth, `viewport ${width}px; desktop=${layout.desktopMedia}; shellPadding=${layout.shellPadding}; overflow: ${layout.offenders.join(" | ")}`).toBeLessThanOrEqual(layout.viewport);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).not.toBe("smooth");
});


test("engagement manager gets a simple decision pipeline without owner controls", async ({ page }) => {
  const user = process.env.ASF_TEST_VP_OIDC_USER || "vp@local.dev";
  const password = process.env.ASF_TEST_VP_OIDC_PASSWORD || "ChangeMeVp123!";

  await loginAs(page, user, password, "Minha fila");
  let engagementId = process.env.ASF_TEST_SERVICE_ENGAGEMENT_ID;
  if (!engagementId) {
    const response = await page.request.get("/api-proxy/api/v1/engagements");
    expect(response.ok()).toBe(true);
    const engagements = await response.json() as Array<{ id: string; name: string }>;
    engagementId = engagements.find((item) => item.name === "Piloto real — Opportunity-to-Proposal Copilot")?.id;
  }
  test.skip(!engagementId, "The commercial pilot engagement is required for the VP plan workspace");
  await expect(page.getByText("Plano → Qualidade → Entregável → Entrega.", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Minha fila", exact: true })).toBeVisible();
  await expect(page.locator('aside a[href="/engagements"]')).toBeVisible();
  await expect(page.locator('aside a[href="/deliverables"]')).toBeVisible();
  await expect(page.locator('aside a[href="/evidence"]')).toBeVisible();
  await expect(page.locator('aside a[href="/approvals"]')).toHaveCount(0);
  await expect(page.locator('aside a[href="/work-queue"]')).toHaveCount(0);
  await expect(page.locator('aside a[href="/runtime"]')).toHaveCount(0);
  await expect(page.locator('aside a[href="/admin/tenants"]')).toHaveCount(0);

  await page.goto("/approvals");
  await expect(page.getByRole("heading", { name: "Aprovações" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Planos de serviço" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Entregáveis de serviço" })).toBeVisible();

  await page.goto("/deliverables");
  await expect(page.getByRole("heading", { name: "Entregáveis para decisão" })).toBeVisible();

  const detailStartedAt = Date.now();
  await page.goto(`/engagements/${engagementId}`);
  await expect(page.getByRole("heading", { name: "Piloto real — Opportunity-to-Proposal Copilot", exact: true })).toBeVisible();
  expect(Date.now() - detailStartedAt, "the warm portal must show the engagement within five seconds").toBeLessThanOrEqual(5_000);
  await expect(page.getByText("Esteira guiada", { exact: true })).toBeVisible();
  await expect(page.getByText("Visão do VP", { exact: true })).toBeVisible();
  const approve = page.getByRole("button", { name: "Aprovar e liberar para o owner" });
  if (await approve.count()) {
    await expect(approve).toBeDisabled();
    await page.getByPlaceholder("Confirme escopo, riscos e condições para iniciar…").fill("Escopo e riscos revisados para validação de usabilidade, sem registrar a decisão.");
    await expect(approve).toBeEnabled();
  } else {
    await expect(page.getByText("approved", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Agora", { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Ativar e materializar a operação" })).toHaveCount(0);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});


test("engagement manager validates a service deliverable in one guided workspace", async ({ page }) => {
  const user = process.env.ASF_TEST_VP_OIDC_USER || "vp@local.dev";
  const password = process.env.ASF_TEST_VP_OIDC_PASSWORD || "ChangeMeVp123!";

  await loginAs(page, user, password, "Minha fila");
  await page.route("**/api-proxy/api/v1/service-deliverables/vp-deliverable-ui", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "vp-deliverable-ui",
        engagement_id: "vp-engagement-ui",
        workstream_id: null,
        template_key: "executive-assessment",
        title: "Assessment executivo de oportunidades",
        description: "Recomendação priorizada para decisão comercial.",
        definition_of_done_json: ["Recomendação executiva apresentada", "Riscos e dependências documentados"],
        acceptance_criteria_json: ["Oportunidades classificadas por valor e viabilidade", "Roadmap consolidado"],
        audience: "client",
        status: "review_ready",
        due_at: null,
        current_revision: 1,
        record_version: 3,
        run_id: null,
        homologation_package_id: null,
        engagement: { id: "vp-engagement-ui", name: "Homologação guiada" },
        offering: { code: "ai_value_discovery", name: "AI Value Discovery" },
        latest_revision: {
          id: "revision-ui",
          revision: 1,
          status: "submitted",
          content_json: {
            title: "Assessment executivo de oportunidades",
            executive_summary: "Três oportunidades priorizadas com recomendação de piloto.",
            content_markdown: "# Recomendação executiva\n\nPriorizar o copiloto comercial como primeiro piloto controlado.",
            evidence_claims: ["Dataset interno avaliado"],
            risks: ["Dependência de dados comerciais consistentes"],
            next_actions: ["Validar sponsor e orçamento do piloto"]
          },
          artifact_refs_json: ["artifact:assessment-v1"],
          evidence_refs_json: ["report:opportunity-ranking"],
          model_call_id: "model-call-ui",
          created_at: new Date().toISOString()
        },
        approval: { id: "approval-ui", status: "pending", comments: "" },
        revisions: []
      })
    });
  });

  await page.goto("/deliverables/vp-deliverable-ui");
  await expect(page.locator("h1").filter({ hasText: "Assessment executivo de oportunidades" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sua decisão: validar o entregável" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Guia de validação" })).toBeVisible();
  await expect(page.getByText("report:opportunity-ranking", { exact: true })).toBeVisible();
  await expect(page.getByText("Dependência de dados comerciais consistentes", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Gerar nova revisão" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submeter ao VP" })).toHaveCount(0);
  const approve = page.getByRole("button", { name: "Aprovar entregável" });
  await expect(approve).toBeDisabled();
  await page.getByPlaceholder("Explique o aceite, os ajustes necessários ou o motivo da rejeição…").fill("Conteúdo, evidências, riscos e critérios revisados pelo VP para decisão.");
  await expect(approve).toBeEnabled();
  await page.route("**/api-proxy/api/v1/service-deliverables/vp-deliverable-ui/decisions", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 504,
        contentType: "application/json",
        body: JSON.stringify({ detail: {
          code: "UPSTREAM_TIMEOUT", message: "A API não respondeu dentro do prazo.",
          correlation_id: "e2e-command-timeout",
        } }),
      });
      return;
    }
    await route.continue();
  });
  await approve.click();
  await expect(page.getByRole("alert").filter({ hasText: "resultado não está confirmado" })).toBeVisible();
  await expect(approve).toBeEnabled();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});


test("operator can ingest and retrieve tenant-isolated knowledge", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page);
  const hasSessionCookies = async () => {
    const names = (await page.context().cookies()).map((cookie) => cookie.name);
    return names.includes("asf_access_token") && names.includes("asf_refresh_token");
  };
  await expect.poll(hasSessionCookies).toBe(true);
  const suffix = Date.now().toString(36);
  const canary = `uiknowledge${suffix}`;
  const basesLoaded = page.waitForResponse((response) =>
    response.request().method() === "GET" && response.url().endsWith("/api-proxy/api/v1/knowledge-bases") && response.ok()
  );
  await page.goto("/knowledge");
  await basesLoaded;
  await expect(page.getByRole("heading", { name: "Knowledge & RAG" })).toBeVisible();
  await expect.poll(hasSessionCookies).toBe(true);
  const baseSelect = page.locator("aside select");
  await expect.poll(() => baseSelect.locator("option").count()).toBeGreaterThan(0);
  const baseCount = await baseSelect.locator("option").count();
  if (baseCount === 1) {
    await page.getByPlaceholder("Nome").fill(`UI knowledge ${suffix}`);
    await page.getByPlaceholder("Descrição").fill("Playwright tenant-isolated knowledge validation");
    await page.getByRole("button", { name: "Criar base isolada" }).click();
    await expect(page.getByText("Base de conhecimento criada somente para o tenant ativo.")).toBeVisible();
  } else {
    await expect(baseSelect).not.toHaveValue("");
  }

  const documentTitle = page.getByPlaceholder("Título do documento");
  const sourceReference = page.getByPlaceholder("Referência da fonte (opcional)");
  const documentContent = page.getByPlaceholder("Cole aqui o conteúdo autorizado deste cliente...");
  await documentTitle.fill("Private UI validation");
  await sourceReference.fill("playwright-release");
  await documentContent.fill(`O marcador privado desta base é ${canary}.`);
  await expect(documentTitle).toHaveValue("Private UI validation");
  await expect(sourceReference).toHaveValue("playwright-release");
  await expect(documentContent).toHaveValue(`O marcador privado desta base é ${canary}.`);
  const indexButton = page.getByRole("button", { name: "Indexar documento" });
  await expect(indexButton).toBeEnabled();
  await expect.poll(hasSessionCookies).toBe(true);
  const [indexResponse] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/documents")),
    indexButton.click()
  ]);
  expect(indexResponse.status()).toBe(200);
  await expect(page.getByText("Documento indexado com chunking semântico e isolamento por tenant.")).toBeVisible();

  await page.getByPlaceholder("Faça uma pergunta sobre este cliente...").fill(`Qual é o marcador ${canary}?`);
  await page.getByRole("button", { name: "Buscar conhecimento" }).click();
  await expect(page.getByText(canary)).toBeVisible();
});


test("completed run exposes the operational cockpit when an audited run is supplied", async ({ page }) => {
  test.skip(!process.env.ASF_TEST_COMPLETED_RUN_ID, "ASF_TEST_COMPLETED_RUN_ID is required for contracted-run E2E");
  test.setTimeout(120_000);
  await login(page);
  await page.route("**/api-proxy/runs/*/stream", async (route) => {
    await route.fulfill({ status: 503, body: "stream interrupted" });
  });
  await page.goto(`/runs/${process.env.ASF_TEST_COMPLETED_RUN_ID}`);
  await expect(page.getByText("Atualizações pausadas.", { exact: false })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Linha de produção" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Topologia" })).toBeVisible();
  await page.getByRole("tab", { name: "Topologia" }).click();
  await expect(page.getByText("Topologia real do workflow")).toBeVisible();
  await page.getByRole("tab", { name: "Qualidade" }).click();
  await expect(page.getByRole("heading", { name: "Matriz de rastreabilidade", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Artifacts e arquivos" }).click();
  await expect(page.getByRole("heading", { name: "Diffs", exact: true })).toBeVisible();
});
