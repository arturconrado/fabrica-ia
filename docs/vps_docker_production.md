# VPS Docker Production Deployment

Este caminho é para uma VPS genérica com Docker, mantendo o contrato production-only da fábrica. Todos os serviços de aplicação rodam como containers Docker; o sandbox continua usando Kubernetes Jobs dentro de um cluster `kind` criado no próprio Docker da VPS.

## Topologia

- Borda pública: Caddy container em `80/443` com TLS automático.
- App público: `https://$ASF_PUBLIC_DOMAIN`.
- API pública: `https://$ASF_API_DOMAIN`.
- OIDC público: `https://$ASF_AUTH_DOMAIN`.
- MinIO Console público: `https://$ASF_MINIO_DOMAIN`.
- Temporal UI somente na rede interna; acesso operacional exige túnel SSH/VPN e não é publicado pelo Caddy.
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

Preencha todos os campos vazios em `.env.vps`: OpenRouter ou OpenAI, LiteLLM, senhas separadas do proprietário e do papel `factory_app`, Temporal Postgres, Keycloak DB, admin Keycloak, MinIO, destino S3 externo de backup, webhook de alertas e identidade inicial (`ASF_VPS_OPERATOR_SUBJECT`, usuário e senha). Use um UUID estável como subject e credenciais PostgreSQL URL-safe, pois entram na DSN. O realm VPS remove usuários demo e o bootstrap associa esse `sub` ao primeiro owner. Em uma instalação Keycloak já existente, confirme o `sub` efetivo antes do bootstrap. Não coloque secrets reais em arquivos versionados.

## Subida

```bash
make vps-docker-up
```

O script:

- valida env obrigatório;
- renderiza `data/keycloak-import/software-factory-realm.vps.json` com o domínio público;
- renderiza a configuração privada do Alertmanager com o webhook informado;
- cria/reutiliza o cluster `kind` `asf-vps`;
- gera `data/kube/asf-vps-internal.kubeconfig` para API/worker;
- aplica namespace, RBAC, NetworkPolicy e PV/PVC do sandbox;
- constrói e carrega `asf-sandbox-runner:local` no kind;
- valida `docker-compose.vps.yml`;
- sobe a stack Docker production-like;
- exige e inicia a réplica dos backups em S3 externo;
- espera health interno da API e health público em `https://$ASF_API_DOMAIN/health`.

Se o DNS/TLS ainda não propagou, use temporariamente:

```bash
ASF_SKIP_PUBLIC_HEALTH=1 make vps-docker-up
```

## Validação

```bash
make vps-docker-validate
```

O validador usa os domínios públicos, obtém token OIDC real no Keycloak e chama `GET /auth/me`. Em seguida executa ContractFlow e ServiceDesk somente pela jornada contratada (contrato/entitlement, prospect, opportunity, MvpSpec, proposta, aprovação e conversão), exige o manifesto AI-native completo, uso e custo reais, ao menos 18 model calls por missão, sete perfis de sandbox, 17 gates, pacote e aprovação humana. Os códigos e as propostas precisam ter fingerprints distintos. Por fim, roda os testes production-stack dentro do container da API sem permitir skip no teste das duas missões.

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
- As jornadas contratadas ContractFlow e ServiceDesk produzem propostas e aplicações distintas, artifacts e arquivos ligados às model calls, evidências reais de backend, frontend, Playwright, axe e segurança em sandbox Kubernetes, 17 gates e delivery package; HRS 100 só depois da decisão humana.
- Run direto e batch técnico retornam `409` em produção; intake em lote permanece disponível via `/api/v1/prospect-batches`.
- Métricas confirmam backups locais/offsite recentes e outbox Temporal sem comandos travados; um alerta de teste chega ao webhook operacional.
- Sandbox rejeita comando não allowlisted e usa PVC com `subPath=tenants/{tenant_id}/{run_id}`.
