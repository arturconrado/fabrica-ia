# Homologation Checklist

Release production-only fica bloqueado até todos os itens críticos passarem no ambiente alvo.

## Runtime
- [x] API valida configuração production-only no startup.
- [x] Rotas operacionais exigem JWT OIDC e tenant.
- [x] Runtime usa LiteLLM com OpenRouter/OpenAI real como provider obrigatório.
- [x] Runs e ações humanas usam Temporal workflow id.
- [x] Sandbox local/process-only foi removido do caminho operacional.
- [x] MCP provider production-named usa allowlist por tenant.

## Factory Operation
- [x] `POST /runs/enterprise` cria run antes de agendar Temporal.
- [x] UI navega para `/runs/{run_id}` com run real tenant-scoped.
- [x] Agent roster, work items, messages, events, artifacts and files remain visible.
- [x] Model calls are exposed globally and per run.
- [x] Sandbox executions are exposed globally and per run.
- [x] Approval, reject and request-changes signal Temporal before local mutation.

## Quality And Evidence
- [x] Requirements, acceptance criteria, traceability, tests, gates and HRS models remain implemented.
- [x] Homologation package generation remains implemented.
- [x] Feedback creates reward and learning records.
- [x] Batch scheduling creates child runs and metrics.

## Required Manual Validation
- [ ] `make docker-full-up` creates/reuses kind cluster `asf-local` through the Docker control container.
- [ ] kind applies sandbox namespace, RBAC, deny-all NetworkPolicy and `asf-sandbox-workspaces` PV/PVC.
- [ ] Docker Compose config succeeds with `ASF_DOCKER_KUBECONFIG=data/kube/asf-local-internal.kubeconfig`.
- [ ] Docker Compose starts API, web, Postgres, Redis, Temporal, worker, MinIO, Keycloak and LiteLLM.
- [ ] MinIO init creates bucket `software-factory-artifacts`.
- [ ] `GET /health` returns ok.
- [ ] Keycloak token accepted by `GET /auth/me`.
- [ ] `Start Enterprise Build` works from UI with real LLM calls.
- [ ] SSE timeline shows progressive agent events.
- [ ] At least five agents change state during operation.
- [ ] `generated_app` is created.
- [ ] Kubernetes sandbox mounts PVC with `subPath={run_id}` and runs `python -m pytest generated_app/tests`.
- [ ] Initial pytest failure and generated correction are recorded.
- [ ] Final pytest passes.
- [ ] 17 quality gates are visible.
- [ ] HRS is calculated and is >= 90.
- [ ] Homologation package is created.
- [ ] Human approval pauses and finalizes the run.
- [ ] Pause/step controls stop between per-agent Temporal activities, not only at persisted API state.
- [ ] Feedback creates `HumanFeedback`, `RewardSignal` and `LearningLesson`.
- [ ] `POST /batches` schedules child runs and metrics.
- [ ] Tenant isolation negative test passes.
- [ ] Protected route without JWT fails.
- [ ] MCP denied tool call is rejected and audited.
- [ ] Sandbox rejects non-allowlisted command and missing workspace PVC.
- [ ] `make docker-full-validate` passes API-container pytest, enterprise run evidence, batch metrics, Docker frontend build and containerized Playwright.
- [ ] `docker compose -f docker-compose.vps.yml config` passes with `.env.vps`.
- [ ] VPS firewall exposes only `22`, `80` and `443` publicly.
- [ ] `make vps-docker-up` starts the VPS production Docker stack.
- [ ] `https://$ASF_PUBLIC_DOMAIN` opens the builder.
- [ ] `https://$ASF_API_DOMAIN/health` returns ok.
- [ ] `https://$ASF_AUTH_DOMAIN` emits OIDC tokens with public issuer.
- [ ] `make vps-docker-validate` passes public API, OIDC, enterprise run, sandbox, HRS, delivery package and batch gates.
