# Agentic Software Factory

Fábrica enterprise de software com agentes LLM reais, workflow durável, governança, rastreabilidade, quality gates, homologação, human-in-the-loop, lote, auditoria e sandbox Kubernetes.

Este repositório segue um contrato **production-only**: desenvolvimento local, homologação e produção usam o mesmo padrão arquitetural. Não existe caminho operacional simplificado para rodar sem LLM real, sem Temporal, sem OIDC ou sem sandbox Kubernetes.

## Requisitos Obrigatórios

- Docker e Docker Compose.
- `kind` e `kubectl` para a validação local full-infra.
- Chave real de LLM exposta como `OPENROUTER_API_KEY` (preferencial) ou `OPENAI_API_KEY`.
- Chave do LiteLLM gateway em `ASF_LITELLM_API_KEY`.
- Node.js 20+ para desenvolvimento do frontend fora do container.

## Subida Local Full-Infra

```bash
cp .env.example .env

export OPENROUTER_API_KEY=sk-or-v1-...
export ASF_LITELLM_API_KEY=change-me-real-litellm-master-key

make local-full-up
make local-full-validate
```

`make local-full-up` cria ou reutiliza o cluster `kind` chamado `asf-local`, gera `data/kube/asf-local-internal.kubeconfig`, aplica namespace/RBAC/NetworkPolicy/PV/PVC do sandbox, carrega a imagem `asf-sandbox-runner:local` e sobe Docker Compose com Postgres, Redis, Temporal, Temporal UI, MinIO, Keycloak, LiteLLM, API, worker e web.

No dev production-like, o host só executa os CLIs de orquestração (`docker`, `kind`, `kubectl`, `curl`). Runtime, backend tests, frontend build, Playwright, LLM gateway, OIDC, Temporal, MinIO e sandbox rodam em containers.

Serviços:

- Web: http://localhost:3000
- API: http://localhost:8000
- Health: http://localhost:8000/health
- Temporal UI: http://localhost:8080
- Keycloak: http://localhost:8081
- MinIO Console: http://localhost:9001
- LiteLLM: http://localhost:4000

Keycloak importa o realm `software-factory`. Usuário local inicial: `operator@local.dev` / `ChangeMe123!`. `make local-full-validate` obtém um token OIDC real por direct grant e exporta `ASF_TEST_API_BASE_URL`, `ASF_TEST_BEARER_TOKEN` e `ASF_TEST_TENANT_ID` para os testes production-stack.

## Operação Principal

1. Abra http://localhost:3000.
2. Informe o token OIDC na barra superior.
3. Descreva a demanda enterprise em linguagem natural.
4. Escolha template, setor, stack, compliance e integrações.
5. Clique em `Start Enterprise Build`.
6. Acompanhe o workspace do run: chat operacional, agentes, handoffs, artifacts, files, tests, quality gates, HRS, sandbox executions, model calls, approval e logs.
7. Use `Pause`, `Resume`, `Step`, `Approve`, `Request Changes` ou `Reject`.
8. Envie feedback para criar `HumanFeedback`, `RewardSignal` e `LearningLesson`.

O fluxo de release exige requisitos P0/P1/P2, acceptance criteria, traceability, generated app, pytest inicial falhando, correção, pytest final passando, 17 quality gates, HRS >= 90, pacote de homologação e aprovação humana.

## APIs Principais

- `GET /health`
- `GET /auth/me`
- `GET /tenants`, `POST /tenants`
- `GET /tenants/{tenant_id}/members`, `POST /tenants/{tenant_id}/members`
- `POST /projects`, `GET /projects`
- `POST /runs`, `POST /runs/enterprise`, `GET /runs/{run_id}`
- `GET /runs/{run_id}/stream`
- `GET /runs/{run_id}/agent-states`
- `GET /runs/{run_id}/agent-messages`
- `GET /runs/{run_id}/work-items`
- `GET /runs/{run_id}/model-calls`
- `GET /runs/{run_id}/sandbox-executions`
- `POST /runs/{run_id}/pause`, `resume`, `step`, `approve`, `reject`, `request-changes`, `cancel`
- `POST /feedback`
- `POST /batches`, `GET /batches/{batch_id}/items`, `GET /batches/{batch_id}/metrics`
- `GET /learning/lessons`
- `GET /model-calls`, `GET /sandbox-executions`, `GET /mcp/tools`

Todas as rotas operacionais, exceto `/health`, exigem JWT OIDC válido e tenant resolvido por `X-Tenant-ID` ou claim `tenant_id`.

## Runtime Production-Only

- Provider: LiteLLM gateway com OpenRouter real por default (`openrouter/openai/gpt-4o-mini`) ou OpenAI direto como alternativa.
- Workflow: Temporal real com worker separado.
- Persistência: PostgreSQL; Alembic para migrations.
- Cache/fanout: Redis disponível na stack.
- Artifacts: MinIO/S3-compatible.
- Auth: OIDC/JWKS via Keycloak local ou provedor corporativo.
- MCP: registry e allowlist por tenant; HTTP/SSE via gateway.
- Sandbox: Kubernetes Jobs, comando allowlisted, limits, non-root, read-only rootfs, `/tmp` efêmero, sem token de service account e RuntimeClass gVisor/Kata quando disponível.

A API valida essa configuração no startup. Se faltar OIDC, LLM real, Temporal, S3 ou sandbox Kubernetes com PVC, a stack não é homologável.

## Validação De Release

```bash
make local-full-up
curl http://localhost:8000/health
make local-full-validate
```

O validador roda health checks, `GET /auth/me`, backend pytest dentro do container da API, enterprise build real com SSE, generated files, duas execuções de teste/sandbox, HRS >= 90, delivery package, batch real, build Docker do frontend e Playwright em container contra a rede Compose. Depois, via UI:

- login/token OIDC real;
- `Start Enterprise Build`;
- timeline SSE com eventos;
- agentes mudando de estado;
- generated app criado;
- sandbox Kubernetes executando `python -m pytest generated_app/tests`;
- falha inicial e correção;
- testes finais passando;
- 17 gates visíveis;
- HRS >= 90;
- homologation package criado;
- approval humana finalizando run;
- feedback gerando reward/lesson;
- `POST /batches` criando runs filhos e métricas.

Para derrubar a stack:

```bash
make local-full-down
ASF_DELETE_KIND=1 make local-full-down
```

## Deploy Em VPS Com Docker

Para uma VPS genérica, use o Compose de produção:

```bash
cp .env.vps.example .env.vps
set -a
. ./.env.vps
set +a

make vps-docker-up
make vps-docker-validate
```

Esse caminho usa [docker-compose.vps.yml](/Users/arturconrado/fabrica-ia/docker-compose.vps.yml:1): Caddy publica apenas `80/443`, todos os bancos/filas/gateways ficam internos, Keycloak usa Postgres, MinIO cria bucket, API/worker acessam o kubeconfig interno do kind e o sandbox roda como Kubernetes Job. O guia completo está em [docs/vps_docker_production.md](/Users/arturconrado/fabrica-ia/docs/vps_docker_production.md:1).

## Produção Kubernetes

Manifests base ficam em `deploy/k8s` para API, web, worker, RBAC e sandbox NetworkPolicy. Antes de produção:

1. Substitua `deploy/k8s/secret.example.yaml` por secrets reais.
2. Configure Postgres, Redis, Temporal, object storage, LiteLLM e OIDC gerenciados ou instalados no cluster.
3. Crie namespace/PVC de sandbox e NetworkPolicy deny-by-default. Em local, isso é automatizado por `deploy/kind/asf-local.yaml` e `deploy/kind/sandbox-workspace-pv.yaml`.
4. Configure RuntimeClass `gvisor`, `kata` ou equivalente.
5. Rode migrations Alembic.
6. Valide tenant isolation, RBAC, MCP allowlist, sandbox e replay/signal Temporal.

## Estado Atual

Implementado neste release: defaults production-only, guard de startup, rotas operacionais sem fallback local, Temporal runner production-named, MCP provider production-named, batch scheduling via Temporal, sandbox Kubernetes obrigatório, automação Docker + kind full-infra, Keycloak realm local, UI sem token dev e docs atualizadas.

Limitação restante: a validação real completa depende de chave OpenRouter ou OpenAI, Docker, `kind`, `kubectl`, DNS/TLS válido na VPS e recursos suficientes. Sem esses recursos, os scripts falham cedo em vez de simular sucesso.
