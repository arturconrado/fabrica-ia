# Phase Checklist

## Production-Only Runtime
- [x] Runtime default is LiteLLM provider.
- [x] Runtime default is Temporal workflow backend.
- [x] Runtime default is Kubernetes sandbox.
- [x] Startup validates Postgres, OIDC, LiteLLM with OpenRouter/OpenAI upstream, Temporal, S3 and sandbox PVC requirements.
- [x] Public operational API no longer exposes local in-process execution paths.
- [x] Frontend no longer sends a development bearer token.
- [x] Keycloak realm import added for local production-like auth.
- [x] Local full-infra path uses Docker Compose plus kind, not a simplified runtime.

## Agent Operations
- [x] Agent states, messages and work items are persisted.
- [x] Agent SOP lifecycle, handoff, thinking, acting, observing and artifact events are emitted.
- [x] LiteLLM model calls are persisted as `ModelCall` evidence.
- [x] Run workspace shows agent roster, transcript, live preview, tests, quality, approval and logs.

## Workflow And HITL
- [x] Runs are scheduled through Temporal with a run row created before UI navigation.
- [x] Temporal worker activity rehydrates the scheduled run id.
- [x] Pause, resume, step, cancel and human decisions require a Temporal workflow id.
- [x] Approval/reject/request-changes send Temporal signals before local state mutation.

## Sandbox, MCP And Storage
- [x] Sandbox rejects non-Kubernetes backend.
- [x] Sandbox requires workspace PVC for Kubernetes Jobs.
- [x] Sandbox executions are persisted, including failure evidence.
- [x] MCP provider uses tenant allowlist and invocation audit.
- [x] Legacy MCP placeholder files removed from the runtime path.
- [x] MinIO/S3 configuration remains required for artifact storage.
- [x] Local kind PV/PVC maps `data/api/workspaces` into sandbox Jobs.
- [x] Sandbox Job mounts workspace with `subPath={run_id}`.
- [x] Local sandbox image includes pytest and runs only the allowlisted command.

## Local Full-Infra Automation
- [x] `deploy/kind/asf-local.yaml` defines the local Kubernetes cluster contract.
- [x] `deploy/kind/sandbox-workspace-pv.yaml` defines the local sandbox PV/PVC.
- [x] `scripts/local-full-infra-up.sh` creates kind, applies sandbox manifests, loads sandbox image and starts Compose.
- [x] `scripts/local-full-infra-validate.sh` gets a real Keycloak token and runs production-stack validation inside containers.
- [x] `scripts/local-full-infra-down.sh` stops Compose and optionally deletes kind.
- [x] `Makefile` keeps direct `local-full-up`, `local-full-validate` and `local-full-down` targets for operators who intentionally install host CLIs.
- [x] Docker Compose includes `web-test` and `web-e2e` profiles for containerized Playwright validation.
- [x] Docker control container exposes `docker-full-up`, `docker-full-validate`, `docker-full-down` and `docker-shell` so local orchestration tools also run in Docker.

## VPS Docker Production
- [x] `docker-compose.vps.yml` defines a production-like Docker stack for a generic VPS.
- [x] Caddy is the only public edge service on `80/443`.
- [x] Postgres, Redis, Temporal, LiteLLM, API, Keycloak and MinIO API are internal-only in the VPS compose.
- [x] Keycloak uses Postgres in the VPS compose.
- [x] Web Docker build accepts production `NEXT_PUBLIC_*` build args.
- [x] VPS scripts render a domain-specific Keycloak realm import.
- [x] VPS scripts create/reuse kind, apply sandbox manifests and load the sandbox runner image.
- [x] `Makefile` exposes `vps-docker-up`, `vps-docker-validate` and `vps-docker-down`.

## Batch
- [x] `POST /batches` schedules enterprise portfolio child runs through Temporal.
- [x] Batch items are tenant-scoped and linked to child runs.
- [x] Batch scheduling metric is persisted.
- [x] Public legacy batch endpoint removed.

## Documentation
- [x] README describes Docker + kind full-infra validation.
- [x] README describes VPS Docker deployment.
- [x] VPS Docker production guide added.
- [x] `.env.example` requires real LLM, Temporal, OIDC, S3 and Kubernetes sandbox settings.
- [x] Homologation checklist updated.
- [x] Batch checklist updated.

## Release Validation Pending In Target Environment
- [ ] `make docker-full-up` with real `OPENROUTER_API_KEY` or `OPENAI_API_KEY`, `ASF_LITELLM_API_KEY` and Docker.
- [ ] `make docker-full-validate` completes against the real local stack.
- [ ] `make vps-docker-up` completes on a real VPS with DNS and TLS.
- [ ] `make vps-docker-validate` completes through public HTTPS domains.
- [ ] Keycloak login/token flow verified end to end.
- [ ] Real LiteLLM/OpenRouter run completes all agents.
- [ ] Temporal workflow resumes from worker restart and receives human signals.
- [ ] Temporal workflow decomposed into per-agent activities for hard pause/step during execution.
- [ ] Kubernetes sandbox Job mounts `asf-sandbox-workspaces` with `subPath={run_id}` and executes pytest.
- [ ] MCP HTTP/SSE gateway tool call succeeds and denied tool call is audited.
- [ ] Playwright run against the real stack covers enterprise build, approval, feedback and batch.

Last update: Docker-first local control container.
