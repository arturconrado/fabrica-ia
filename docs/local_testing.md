# Local Full-Infra Production-Like Testing

## Required Environment

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
export ASF_LITELLM_API_KEY=change-me-real-litellm-master-key
```

## Stack

```bash
cp .env.example .env
make docker-full-up
make docker-full-validate
```

`make docker-full-up` usa o container de controle `asf-local-control` para criar o cluster `kind` `asf-local`, gerar o kubeconfig interno em `data/kube/asf-local-internal.kubeconfig`, aplicar namespace/RBAC/NetworkPolicy/PV/PVC do sandbox, carregar `asf-sandbox-runner:local` e subir Docker Compose com Postgres, Redis, Temporal, Temporal UI, MinIO, Keycloak, LiteLLM, API, worker e web.

The host only needs Docker access. The control container runs orchestration CLIs (`docker`, `kind`, `kubectl`, `curl`, Python and Make). Runtime services, backend tests, frontend build, Playwright and sandbox execution run in Docker containers.

OpenRouter is the default upstream for LiteLLM. OpenAI direct keys remain supported as a fallback by setting `OPENAI_API_KEY`, but release validation should prefer `OPENROUTER_API_KEY` with `ASF_DEFAULT_MODEL=openrouter/openai/gpt-4o-mini`.

Open:

- Web: http://localhost:3000
- API health: http://localhost:8000/health
- Temporal UI: http://localhost:8080
- Keycloak: http://localhost:8081
- MinIO: http://localhost:9001
- LiteLLM: http://localhost:4000

## Manual Homologation Flow

1. Get a Keycloak access token for `operator@local.dev`.
2. Paste the token into the UI `OIDC bearer token` control.
3. Start `Enterprise Build` from `/`.
4. Confirm the run workspace shows chat, agent activity, live preview, quality rail and evidence.
5. Confirm at least five agents change state while SSE events arrive.
6. Use Pause, Step and Resume.
7. Confirm generated files, diffs, model calls and sandbox executions exist.
8. Confirm Kubernetes sandbox mounts `asf-sandbox-workspaces` with `subPath={run_id}` and executes `python -m pytest generated_app/tests`.
9. Confirm initial failed pytest, correction and final passing pytest.
10. Confirm HRS >= 90 and 17 quality gates.
11. Approve the run.
12. Submit feedback and confirm learning/reward records.
13. Start `POST /batches` from the UI and confirm child runs plus metrics.
14. Open `/runtime` and confirm model calls, sandbox executions and MCP tools.

## Automated Full Validation

```bash
make docker-full-validate
```

The script:

- gets a real OIDC token from Keycloak for `operator@local.dev`;
- exports `ASF_TEST_API_BASE_URL`, `ASF_TEST_BEARER_TOKEN` and `ASF_TEST_TENANT_ID`;
- verifies API, web, Temporal UI, Keycloak, MinIO, LiteLLM, NetworkPolicy and PVC;
- runs backend production-stack pytest inside the API container;
- starts a real enterprise build and waits for SSE, generated files, agents, model calls, two sandbox/test executions, HRS >= 90, quality gates and delivery package;
- starts a real batch and checks items plus metrics;
- builds the frontend with Docker Compose and runs Playwright in a Docker container against the Compose network.

## API Smoke

```bash
TOKEN="<oidc-access-token>"
RUN_ID=$(curl -s -X POST 'http://localhost:8000/runs/enterprise' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Crie uma plataforma enterprise com RBAC, auditoria, SLA e integração ERP.","project_name":"Enterprise Quality Platform","template":"enterprise-saas","industry":"financial_services","quality_profile":"regulated_enterprise","compliance":["SOC2","LGPD","ISO27001"],"integrations":["SSO/OIDC","ERP","Data Warehouse"],"data_sensitivity":"confidential"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -H "Authorization: Bearer $TOKEN" -H 'X-Tenant-ID: local-dev' http://localhost:8000/runs/$RUN_ID/agent-states
curl -H "Authorization: Bearer $TOKEN" -H 'X-Tenant-ID: local-dev' http://localhost:8000/runs/$RUN_ID/model-calls
curl -H "Authorization: Bearer $TOKEN" -H 'X-Tenant-ID: local-dev' http://localhost:8000/runs/$RUN_ID/sandbox-executions
```

## Teardown

```bash
make docker-full-down
ASF_DELETE_KIND=1 make docker-full-down
```
