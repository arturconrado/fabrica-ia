import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";


async function login(page: Page) {
  await page.goto("/auth/login?returnTo=%2Fdashboard", { waitUntil: "commit" });
  await page.locator("#username").fill(process.env.ASF_TEST_OIDC_USER || "operator@local.dev");
  await page.locator("#password").fill(process.env.ASF_TEST_OIDC_PASSWORD || "ChangeMe123!");
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL((url) => url.origin === "http://localhost:3000" && url.pathname === "/dashboard");
  await expect(page.locator("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
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


test("service delivery catalog exposes the eight real operational offerings", async ({ page }) => {
  await login(page);
  await page.goto("/service-catalog");
  await expect(page.getByRole("heading", { name: "Catálogo de serviços" })).toBeVisible();
  for (const offering of [
    "AI Value Discovery",
    "AI Governance & Risk Framework",
    "AI Enterprise Launchpad",
    "AI Workforce Productivity Accelerator",
    "AI Engineering Productivity Accelerator",
    "AI Use Case Pilot Sprint",
    "AI Office as a Service",
    "AI Adoption Kit & Governance Cockpit",
  ]) {
    await expect(page.getByRole("heading", { name: offering })).toBeVisible();
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
    await page.waitForTimeout(250);
    await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
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
  await page.goto(`/runs/${process.env.ASF_TEST_COMPLETED_RUN_ID}`);
  await expect(page.getByRole("tab", { name: "Linha de produção" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Topologia" })).toBeVisible();
  await page.getByRole("tab", { name: "Topologia" }).click();
  await expect(page.getByText("Topologia real do workflow")).toBeVisible();
  await page.getByRole("tab", { name: "Qualidade" }).click();
  await expect(page.getByText("Matriz de rastreabilidade")).toBeVisible();
  await page.getByRole("tab", { name: "Artifacts e arquivos" }).click();
  await expect(page.getByText("Diffs")).toBeVisible();
});
