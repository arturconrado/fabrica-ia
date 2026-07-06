# VPS Docker Production Deployment

Este caminho é para uma VPS genérica com Docker, mantendo o contrato production-only da fábrica. Todos os serviços de aplicação rodam como containers Docker; o sandbox continua usando Kubernetes Jobs dentro de um cluster `kind` criado no próprio Docker da VPS.

## Topologia

- Borda pública: Caddy container em `80/443` com TLS automático.
- App público: `https://$ASF_PUBLIC_DOMAIN`.
- API pública: `https://$ASF_API_DOMAIN`.
- OIDC público: `https://$ASF_AUTH_DOMAIN`.
- MinIO Console público: `https://$ASF_MINIO_DOMAIN`.
- Temporal UI público: `https://$ASF_TEMPORAL_DOMAIN`.
- Serviços internos sem porta pública: Postgres, Redis, Temporal, LiteLLM, API, worker, Keycloak, MinIO API.
- Sandbox: kind em Docker, namespace `software-factory-sandbox`, NetworkPolicy deny-all e PVC `asf-sandbox-workspaces`.

## Requisitos Da VPS

- Ubuntu/Debian ou Linux equivalente.
- Docker Engine e Docker Compose plugin.
- `kind`, `kubectl`, `curl` e `python3`.
- DNS `A/AAAA` apontando todos os domínios para a VPS.
- Firewall liberando somente `22`, `80` e `443` para público.
- Chave real de LLM em `OPENROUTER_API_KEY` (preferencial) ou `OPENAI_API_KEY`.

## Configuração

```bash
cp .env.vps.example .env.vps
set -a
. ./.env.vps
set +a
```

Preencha todos os campos vazios em `.env.vps`: OpenRouter ou OpenAI, LiteLLM, senhas de Postgres, Temporal Postgres, Keycloak DB, admin Keycloak e MinIO. Não coloque secrets reais em arquivos versionados.

## Subida

```bash
make vps-docker-up
```

O script:

- valida env obrigatório;
- renderiza `data/keycloak-import/software-factory-realm.vps.json` com o domínio público;
- cria/reutiliza o cluster `kind` `asf-vps`;
- gera `data/kube/asf-vps-internal.kubeconfig` para API/worker;
- aplica namespace, RBAC, NetworkPolicy e PV/PVC do sandbox;
- constrói e carrega `asf-sandbox-runner:local` no kind;
- valida `docker-compose.vps.yml`;
- sobe a stack Docker production-like;
- espera health interno da API e health público em `https://$ASF_API_DOMAIN/health`.

Se o DNS/TLS ainda não propagou, use temporariamente:

```bash
ASF_SKIP_PUBLIC_HEALTH=1 make vps-docker-up
```

## Validação

```bash
make vps-docker-validate
```

O validador usa os domínios públicos, obtém token OIDC real no Keycloak, chama `GET /auth/me`, inicia `POST /runs/enterprise`, espera quality gates, sandbox executions, test reports, HRS >= 90 e delivery package, cria um batch e roda pytest production-stack dentro do container da API.

## Operação

```bash
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml logs -f api temporal-worker caddy
make vps-docker-down
ASF_DELETE_KIND=1 make vps-docker-down
```

## Gates De Release

- `docker compose -f docker-compose.vps.yml config` passa.
- Só Caddy publica portas externas `80/443`.
- `https://$ASF_PUBLIC_DOMAIN` abre.
- `https://$ASF_API_DOMAIN/health` retorna ok.
- Keycloak emite token OIDC com issuer público.
- API aceita token por `GET /auth/me`.
- Enterprise build real produz eventos, agentes, generated app, pytest em sandbox Kubernetes, HRS >= 90, 17 gates e delivery package.
- Batch cria 3 child runs e métricas.
- Sandbox rejeita comando não allowlisted e usa PVC com `subPath={run_id}`.
