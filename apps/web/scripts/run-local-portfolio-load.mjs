import { chromium } from "@playwright/test";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";


const allProfiles = ["baseline-2", "load-20", "load-50", "stress-200", "spike-500", "soak-20"];
const profiles = process.env.ASF_LOAD_PROFILES
  ? process.env.ASF_LOAD_PROFILES.split(",").map((value) => value.trim()).filter(Boolean)
  : allProfiles;
if (!profiles.length || profiles.some((profile) => !allProfiles.includes(profile))) {
  throw new Error("ASF_LOAD_PROFILES contains an unknown or empty profile");
}
const repoRoot = resolve(import.meta.dirname, "../../..");
const outputDir = process.env.ASF_PRODUCTION_E2E_LOAD_DIR
  || resolve(repoRoot, "artifacts/production-readiness/production-candidate/load");
const webOrigin = (process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000").replace(/\/$/, "");
const apiOrigin = (process.env.ASF_RELEASE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const oidcIssuer = (process.env.OIDC_PUBLIC_ISSUER_URL || "http://localhost:8081/realms/software-factory").replace(/\/$/, "");
const tenantId = process.env.ASF_LOAD_TENANT_ID || process.env.ASF_RELEASE_TENANT_ID || "";
const vpTenantId = process.env.ASF_LOAD_VP_TENANT_ID || tenantId;
const apiContainerName = process.env.ASF_LOAD_API_CONTAINER || "fabrica-ia-api-1";
const apiImageName = process.env.ASF_LOAD_API_IMAGE || "fabrica-ia-api";
const loadRunner = process.env.ASF_LOAD_RUNNER || "docker";
if (!["docker", "host"].includes(loadRunner)) {
  throw new Error("ASF_LOAD_RUNNER must be docker or host");
}

for (const name of [
  "ASF_TEST_OIDC_USER",
  "ASF_TEST_OIDC_PASSWORD",
  "ASF_TEST_VP_OIDC_USER",
  "ASF_TEST_VP_OIDC_PASSWORD",
]) {
  if (!process.env[name]) throw new Error(`${name} is required`);
}
if (!tenantId || !vpTenantId) throw new Error("ASF_LOAD_TENANT_ID and ASF_LOAD_VP_TENANT_ID are required");
for (const origin of [webOrigin, apiOrigin, oidcIssuer]) {
  const hostname = new URL(origin).hostname;
  if (!["localhost", "127.0.0.1", "::1"].includes(hostname)) {
    throw new Error(`local load wrapper refuses remote origin: ${origin}`);
  }
}

mkdirSync(resolve(repoRoot, "artifacts"), { recursive: true });
const lockDirectory = resolve(repoRoot, "artifacts/.portfolio-load.lock");
function acquireLoadLock() {
  try {
    mkdirSync(lockDirectory);
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
    const recordedPid = Number.parseInt(
      readFileSync(join(lockDirectory, "pid"), "utf8").trim(),
      10,
    );
    let active = false;
    if (Number.isInteger(recordedPid) && recordedPid > 0) {
      try {
        process.kill(recordedPid, 0);
        active = true;
      } catch {
        active = false;
      }
    }
    if (active) {
      throw new Error(`another portfolio load harness is active (pid ${recordedPid})`);
    }
    rmSync(lockDirectory, { recursive: true, force: true });
    mkdirSync(lockDirectory);
  }
  writeFileSync(join(lockDirectory, "pid"), `${process.pid}\n`, { mode: 0o600 });
}

function releaseLoadLock() {
  rmSync(lockDirectory, { recursive: true, force: true });
}

acquireLoadLock();
process.once("exit", releaseLoadLock);
process.once("SIGINT", () => process.exit(130));
process.once("SIGTERM", () => process.exit(143));

const browser = await chromium.launch({ headless: true });
const temporaryOutput = loadRunner === "docker"
  ? mkdtempSync(join(resolve(repoRoot, "artifacts"), ".asf-portfolio-load-"))
  : mkdtempSync(join(tmpdir(), "asf-portfolio-load-"));

function containerSignature() {
  const container = execFileSync(
    "docker",
    [
      "inspect",
      "--format",
      "{{.Id}}|{{.RestartCount}}|{{.State.StartedAt}}",
      apiContainerName,
    ],
    { encoding: "utf8" },
  ).trim();
  const processes = execFileSync(
    "docker",
    ["top", apiContainerName, "-eo", "pid,ppid,command"],
    { encoding: "utf8" },
  ).trim();
  return `${container}\n${processes}`;
}

function signatureHash(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function browserCredential(user, password, expectedRole, credentialTenantId) {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(`${webOrigin}/auth/login?returnTo=%2Fdashboard`, { waitUntil: "commit" });
    await page.locator("#username").fill(user);
    await page.locator("#password").fill(password);
    await page.locator("#kc-login").click();
    await page.waitForURL(
      (url) => url.origin === webOrigin && !url.pathname.startsWith("/auth/"),
      { timeout: 30_000, waitUntil: "commit" },
    );
    const cookies = await context.cookies();
    const accessToken = cookies.find((cookie) => cookie.name === "asf_access_token")?.value || "";
    const refreshToken = cookies.find((cookie) => cookie.name === "asf_refresh_token")?.value || "";
    if (!accessToken || !refreshToken) throw new Error(`${expectedRole} OIDC session did not produce renewable credentials`);
    const sessionResponse = await fetch(`${apiOrigin}/auth/session`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Tenant-ID": credentialTenantId,
        Accept: "application/json",
      },
      signal: AbortSignal.timeout(15_000),
    });
    if (!sessionResponse.ok) {
      throw new Error(`${expectedRole} OIDC session validation returned HTTP ${sessionResponse.status}`);
    }
    const session = await sessionResponse.json();
    if (session.me?.role !== expectedRole) {
      throw new Error(`OIDC role mismatch: expected ${expectedRole}`);
    }
    return { accessToken, refreshToken };
  } finally {
    await context.close();
  }
}

try {
  const owner = await browserCredential(
    process.env.ASF_TEST_OIDC_USER,
    process.env.ASF_TEST_OIDC_PASSWORD,
    "owner",
    tenantId,
  );
  const vp = await browserCredential(
    process.env.ASF_TEST_VP_OIDC_USER,
    process.env.ASF_TEST_VP_OIDC_PASSWORD,
    "engagement_manager",
    vpTenantId,
  );
  const loadEnv = {
    ...process.env,
    ASF_LOAD_BEARER_TOKEN: owner.accessToken,
    ASF_LOAD_OWNER_REFRESH_TOKEN: owner.refreshToken,
    ASF_LOAD_OWNER_CLIENT_ID: process.env.OIDC_CLIENT_ID || "software-factory-web",
    ASF_LOAD_TENANT_ID: tenantId,
    ASF_LOAD_VP_BEARER_TOKEN: vp.accessToken,
    ASF_LOAD_VP_REFRESH_TOKEN: vp.refreshToken,
    ASF_LOAD_VP_CLIENT_ID: process.env.OIDC_CLIENT_ID || "software-factory-web",
    ASF_LOAD_VP_TENANT_ID: vpTenantId,
    ASF_LOAD_OIDC_TOKEN_URL: `${oidcIssuer}/protocol/openid-connect/token`,
  };
  for (const profile of profiles) {
    const profileOutput = join(temporaryOutput, profile);
    mkdirSync(profileOutput, { recursive: true });
    const targetBefore = containerSignature();
    const harnessArguments = [
      resolve(repoRoot, "scripts/portfolio-load-test.py"),
      "--profile",
      profile,
      "--base-url",
      apiOrigin,
      "--output-dir",
      profileOutput,
    ];
    if (process.env.ASF_LOAD_DURATION_SCALE) {
      harnessArguments.push("--duration-scale", process.env.ASF_LOAD_DURATION_SCALE);
    }
    if (process.env.ASF_LOAD_WARMUP_REQUESTS) {
      harnessArguments.push("--warmup-requests", process.env.ASF_LOAD_WARMUP_REQUESTS);
    }
    let result;
    if (loadRunner === "docker") {
      const containerEnv = {
        ...loadEnv,
        ASF_LOAD_OIDC_TOKEN_URL: "http://keycloak:8080/realms/software-factory/protocol/openid-connect/token",
      };
      const forwardedEnvironment = [
        "ASF_LOAD_BEARER_TOKEN",
        "ASF_LOAD_OWNER_REFRESH_TOKEN",
        "ASF_LOAD_OWNER_CLIENT_ID",
        "ASF_LOAD_OWNER_CLIENT_SECRET",
        "ASF_LOAD_TENANT_ID",
        "ASF_LOAD_VP_BEARER_TOKEN",
        "ASF_LOAD_VP_REFRESH_TOKEN",
        "ASF_LOAD_VP_CLIENT_ID",
        "ASF_LOAD_VP_CLIENT_SECRET",
        "ASF_LOAD_VP_TENANT_ID",
        "ASF_LOAD_OIDC_TOKEN_URL",
        "ASF_PRODUCTION_E2E_RUN_ID",
      ].flatMap((name) => containerEnv[name] ? ["--env", name] : []);
      const containerArguments = [
        "run",
        "--rm",
        "--network",
        `container:${apiContainerName}`,
        "--volume",
        `${resolve(repoRoot, "scripts")}:/load-scripts:ro`,
        "--volume",
        `${profileOutput}:/load-output`,
        ...forwardedEnvironment,
        apiImageName,
        "python",
        "/load-scripts/portfolio-load-test.py",
        ...harnessArguments.slice(1).map((value) => (
          value === apiOrigin ? "http://127.0.0.1:8000"
            : value === profileOutput ? "/load-output"
              : value
        )),
      ];
      result = spawnSync(
        "docker",
        containerArguments,
        { cwd: repoRoot, env: containerEnv, stdio: "inherit" },
      );
    } else {
      result = spawnSync(
        "python3",
        harnessArguments,
        { cwd: repoRoot, env: loadEnv, stdio: "inherit" },
      );
    }
    const targetAfter = containerSignature();
    const targetStable = targetBefore === targetAfter;
    mkdirSync(outputDir, { recursive: true });
    const stem = `portfolio-v2-${profile}`;
    const jsonSource = join(profileOutput, `${stem}.json`);
    const markdownSource = join(profileOutput, `${stem}.md`);
    const jsonTarget = join(outputDir, `${stem}.json`);
    const markdownTarget = join(outputDir, `${stem}.md`);
    const sourceArtifactsPresent = existsSync(jsonSource) && existsSync(markdownSource);
    if (sourceArtifactsPresent) {
      const report = JSON.parse(readFileSync(jsonSource, "utf8"));
      report.target_instance = {
        container_name: apiContainerName,
        signature_before_sha256: signatureHash(targetBefore),
        signature_after_sha256: signatureHash(targetAfter),
        stable: targetStable,
      };
      if (!targetStable) {
        report.status = "failed";
        report.invalid_reason = "target container changed or restarted during load";
      }
      writeFileSync(jsonTarget, `${JSON.stringify(report, null, 2)}\n`);
      copyFileSync(markdownSource, markdownTarget);
      writeFileSync(
        markdownTarget,
        `${readFileSync(markdownTarget, "utf8")}\n- Target instance stable: **${targetStable ? "yes" : "no"}** (before ${report.target_instance.signature_before_sha256}, after ${report.target_instance.signature_after_sha256})\n`,
      );
    } else {
      writeFileSync(
        jsonTarget,
        `${JSON.stringify({
          schema_version: "service-portfolio-load-v2",
          profile,
          status: "failed",
          invalid_reason: "load runner did not produce both JSON and Markdown evidence",
          target_instance: {
            container_name: apiContainerName,
            signature_before_sha256: signatureHash(targetBefore),
            signature_after_sha256: signatureHash(targetAfter),
            stable: targetStable,
          },
        }, null, 2)}\n`,
      );
    }
    if (result.status !== 0) {
      throw new Error(`${profile} load profile failed`);
    }
    if (!sourceArtifactsPresent) {
      throw new Error(`${profile} load profile produced no evidence artifacts`);
    }
    if (!targetStable) {
      throw new Error(`${profile} target container changed or restarted during load`);
    }
  }
} finally {
  await browser.close();
  rmSync(temporaryOutput, { recursive: true, force: true });
  releaseLoadLock();
}
