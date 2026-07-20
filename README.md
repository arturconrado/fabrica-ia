# Agentic Software Factory

Command center local-first para operar uma fábrica multiagente com OIDC, isolamento por tenant, ledger append-only, artifacts Markdown, RAG, quality gates, homologação e decisões humanas.

O corte atual é um piloto assistido para cinco clientes, com capacidade técnica configurável de até dez tenants. Cada cliente possui tenant, memberships, corpus RAG, objetos, runs, custos e histórico próprios. O operador pode alternar entre clientes; consultas de negócio nunca agregam seus conteúdos.

## Subida local

Requisitos: Docker com Compose e uma chave nova de provedor LLM. Uma chave anteriormente compartilhada em conversa ou log deve ser revogada antes do uso.

```bash
cp .env.example .env
# troque os placeholders locais; a stack base mantém geração técnica desabilitada
docker compose up --build
```

Para executar missões gerativas reais, configure uma chave nova, `ASF_LITELLM_API_KEY`, `ASF_ENCRYPTION_KEY` e os modelos upstream, então use `make docker-full-up`. Esse perfil sobe Temporal, MinIO e um cluster Kind para Jobs de sandbox sem rede.

Serviços principais:

- Interface: `http://localhost:3000`
- API: `http://localhost:8000`
- Keycloak: `http://localhost:8081`
- LiteLLM: `http://localhost:4000`
- MinIO: `http://localhost:9000` (console em `http://localhost:9001`)
- Health: `http://localhost:8000/health`

As portas do Compose local são ligadas apenas a `127.0.0.1`. Temporal UI em `http://localhost:8080` é adicionada pelo perfil full. Prometheus, Grafana, Tempo e o collector OTLP também são adicionados nesse perfil; API e worker exportam spans sem conteúdo de prompt para o collector interno.

O Compose executa migrations, importa o realm OIDC com PKCE, cria somente o tenant local explicitamente configurado e associa o `sub` estável do operador. Não existe seed de runtime, usuário de demonstração, botão de token manual ou dataset fictício.

Credencial local inicial do realm de desenvolvimento:

- usuário: `operator@local.dev`
- senha: `ChangeMe123!`

Essa senha existe apenas no realm local versionado. Produção exige provedor OIDC e usuário configurados externamente.

## Autenticação e segurança

A interface usa Authorization Code + PKCE. O BFF do Next.js mantém access e refresh tokens em cookies `HttpOnly`, encaminha o bearer e o tenant à API e centraliza refresh, expiração e logout. Tokens não são armazenados no DOM, `localStorage`, `sessionStorage` ou variáveis `NEXT_PUBLIC_*`.

Papéis:

- Operação: `owner`, `super_admin`, `tenant_admin`, `engagement_manager`, `consultant`, `admin`, `operator`.
- Decisão: `client_sponsor`, `process_owner`, `reviewer`; `auditor` possui leitura sem decisão.
- Administração: `owner`, `super_admin`, `tenant_admin`, `admin`, conforme a rota.

O servidor aplica RBAC; esconder um link na UI não concede nem revoga acesso. PostgreSQL usa contexto transacional e RLS forçada. Artifacts têm `audience=internal|reviewer|client`; a API de revisão expõe apenas artifacts promovidos e manifests sanitizados.

## Operação dos cinco clientes

Para criar os cinco tenants com o mesmo operador, obtenha o `sub` exato no OIDC e execute o bootstrap uma vez por cliente:

```bash
docker compose run --rm local-onboarding python -m app.cli.bootstrap_tenant \
  --tenant-id cliente-01 --tenant-name 'Cliente 01' \
  --subject 'OIDC-SUBJECT-DO-OPERADOR' \
  --confirm 'bootstrap assisted pilot tenant'
```

Repita com IDs e nomes distintos. O portfólio enumera somente memberships operacionais ativas e calcula cada resumo em uma sessão vinculada ao tenant correspondente. Veja [operations-runbook.md](docs/operations-runbook.md).

O Service Delivery OS adiciona uma camada de operação acima das runs técnicas:

- `/clients` apresenta apenas os cinco clientes autorizados; `/clients/[tenantId]` só carrega o Cliente 360 depois da troca segura do tenant ativo.
- `/service-catalog` contém exatamente oito ofertas globais versionadas. Elas são referência operacional e não seed demonstrativo.
- `/engagements` instancia uma versão contratada, gera um plano específico com IA e exige aprovação humana antes de materializar workstreams, fila, entregáveis e equipe AI.
- `/work-queue` aplica WIP determinístico de cinco itens globais e dois por cliente. Override exige justificativa e evento.
- `/deliverables` mantém revisões, audiência, evidências, model call, decisão humana e entrega final separadas por tenant.
- `/agents` governa lacunas, candidatos, três avaliações reais, homologação humana e alocação. Lacunas de ferramenta ficam bloqueadas para desenvolvimento humano.

Na ativação, a plataforma aloca somente agentes-base já homologados e adequados à oferta. Um candidato gerado por IA nunca recebe versão utilizável antes de avaliação e decisão administrativa. O Pilot Sprint mantém `rapid_mvp_factory` e aciona a fábrica técnica existente sem renomear contratos ou runs históricas.

### Knowledge e RAG

1. Selecione o tenant antes de abrir `/knowledge`.
2. Crie uma base e ingira somente texto autorizado do cliente.
3. A indexação persiste documento, chunks, checksum, storage key prefixada e evento no ledger.
4. A busca híbrida/extrativa é local e tenant-scoped.
5. Geração pelo LLM exige opt-in explícito no bootstrap; somente os trechos daquele tenant são enviados ao provider.
6. Consultar um ID conhecido de outro tenant retorna 404/vazio.

Consultas RAG, rejeições e falhas não geram XP.

### Missões e executor suportado

O intake registra prospect, oportunidade, briefing, escopo, proposta, contrato, entitlement e aprovação reais. Runs técnicas diretas são exclusivas dos testes. Em perfis operacionais, a criação de ASF Run passa pelo fluxo contratado e recusa qualquer blueprint sem executor versionado.

Novas runs operacionais usam `software_factory_ai_native_v2` fixado na política v2.13. O executor lê nodes, edges, condições e limites do YAML persistido; cada papel recebe contexto tenant-scoped e produz seu contrato Pydantic específico, normalizado somente após validação. Artifacts e arquivos carregam `model_call_id` e `step_execution_id`; código só entra em `generated_app/`, e atualizações exigem o hash da versão-base. Runs v1, v2.11 e v2.12 permanecem reproduzíveis e consultáveis.

Novas runs também registram `executor_protocol_version=segmented-output-v1`. Temporal congela um plano curto por node e executa uma activity por unidade; artifacts são divididos em até 12 seções e o Engineer em lotes de até quatro arquivos. Cada unidade possui identidade idempotente, heartbeat, limite de tentativas/continuações, hash, trace e vínculo com a model call. A montagem e a transição só ocorrem quando todas as unidades foram confirmadas. Pause/resume operacional e pausa por orçamento aguardam signal; isolamento nunca é repetido automaticamente.

O workflow v2.13 declara budgets, reservas e fontes por node. RAG envia apenas chunks híbridos relevantes; reviewer recebe requisitos/arquitetura/diffs, QA recebe critérios/testes/evidências e o Quality Governor recebe gates/hashes/resumos. Digests por checksum são privados do tenant. Apenas prompts/skills globais estáveis são marcados para cache do provider.

Briefing, escopo, proposta, arquitetura, código, testes e relatórios vêm das respostas reais do modelo. Pricing, entitlement, orçamento, comandos permitidos, sandbox, 17 gates, HRS e aprovação humana permanecem determinísticos. O perfil completo bloqueia novas chamadas em US$ 15 por run e exige evidência de uso real. AFlow continua apenas como referência conceitual e não aparece na interface enquanto não houver motor verificável.

## Interface operacional

A UI está em pt-BR, usa sidebar/drawer responsivo, tema escuro por padrão e tema claro acessível. Áreas principais:

- Command Center multi-tenant com próxima ação, runs, bloqueios, HRS, custo e proveniência.
- Fábrica, programas, projetos, oportunidades, componentes, MVP runs, runs e batches.
- Cockpit MetaGPT com papéis/SOPs reais, handoffs, artifacts, gates e grafo derivado do YAML.
- Aprovações, evidências e entregas em workspace seguro para o revisor.
- Knowledge/RAG, agentes, atividade de IA, runtime, conectores e learning.
- Contratos, entitlements, tenants e membros para administradores.

Valores ausentes aparecem como estado vazio ou `—`; nunca são convertidos em créditos, contagens ou histórias inventadas.

## APIs novas

- `GET /api/v1/operator/service-portfolio`
- `GET /api/v1/operator/work-queue`
- `GET /api/v1/operator/capacity`
- `GET /api/v1/client-operations/overview`
- `GET /api/v1/client-operations/events`
- `GET /api/v1/service-catalog/offerings`
- `GET|POST /api/v1/engagements`
- `GET /api/v1/engagements/{id}`
- `POST /api/v1/engagements/{id}/plans/generate`
- `POST /api/v1/engagements/{id}/plans/{version}/approve`
- `POST /api/v1/engagements/{id}/activate`
- `GET /api/v1/service-deliverables`
- `POST /api/v1/service-deliverables/{id}/submit`
- `POST /api/v1/service-deliverables/{id}/decisions`
- `POST /api/v1/service-deliverables/{id}/deliver`
- `GET /api/v1/outcome-metrics`
- `POST /api/v1/engagements/{id}/outcomes`
- `POST /api/v1/outcome-metrics/{id}/observations`
- `GET /api/v1/agent-catalog`
- `GET|POST /api/v1/agent-gaps`
- `POST /api/v1/agent-gaps/{id}/generate-candidate`
- `POST /api/v1/agent-candidates/{id}/evaluate`
- `POST /api/v1/agent-candidates/{id}/decisions`
- `POST /api/v1/agent-assignments`
- `GET /api/v1/operator/portfolio`
- `GET /api/v1/operator/overview`
- `GET /runs/{id}/workspace`
- `GET /runs/{id}/validation-manifest`
- `GET /runs/{id}/token-analysis`
- `GET /runs/{id}/execution-units`
- `GET /runs/{id}/reliability`
- `GET /api/v1/operator/ai-cost-analysis`
- `GET /api/v1/operator/slo`
- `GET /api/v1/admin/platform-readiness`
- `GET /api/v1/ai-invocations/{id}`
- `GET /workflows/{id}/topology`
- `GET /api/v1/review/inbox`
- `GET /api/v1/review/items/{id}`
- `POST /api/v1/review/items/{id}/decisions`
- `GET /api/v1/gamification/profile`
- `GET /api/v1/gamification/events`
- `GET /api/v1/component-instances`
- `GET /api/v1/mvp-runs`
- `GET /learning/signals`
- `GET /learning/candidates`
- `POST /learning/candidates/{id}/evaluate`
- `POST /learning/candidates/{id}/decisions`
- `POST /learning/policies/{id}/rollback`
- `POST /learning/policies/{id}/promote-stage`
- `POST /learning/cost-policies/proposals`
- `GET /api/v1/learning/effective-policy`
- `GET /api/v1/admin/global-learning/policies`
- `POST /api/v1/admin/global-learning/candidates/{id}/promote`
- `POST /api/v1/admin/global-learning/policies/{id}/deployments`
- `POST /api/v1/admin/global-learning/deployments/{id}/rollback`

Os tipos da web são gerados a partir do OpenAPI:

```bash
cd apps/web
OPENAPI_URL=http://localhost:8000/openapi.json npm run generate:api
```

## Gamificação auditável

XP é uma projeção descartável do ledger e não altera HRS, gates, permissões ou decisões humanas.

| Evento | XP |
|---|---:|
| `knowledge.document_indexed` | 10 |
| `ai.mvp.scoped` | 20 |
| `mvp_run.asf_run_created` | 20 |
| `quality.gate_passed` | 10 |
| `homologation.package_created` | 50 |
| `approval.approved` | 20 |
| `deliverable.approved_and_delivered` | 100 |

Níveis: Iniciação (0), Operação (100), Orquestração (300), Homologação (700) e Excelência (1.500). A unicidade por tenant, ledger, tipo de evento e beneficiário impede pontuação duplicada.

## Validação

```bash
cd apps/api && uv run pytest
cd apps/web && npm run build
cd apps/web && npm run test:e2e
docker compose config
```

O E2E requer a stack OIDC em execução. A validação production-like completa usa:

```bash
make docker-doctor
make docker-full-up
make docker-full-validate
```

O validador completo cria duas missões distintas, ContractFlow e ServiceDesk, e falha se seus códigos/propostas forem equivalentes, se faltar vínculo modelo→artifact/arquivo, se o custo exceder US$ 15, se algum perfil de sandbox falhar ou se a aplicação não inicializar. Nunca declare homologação final sem essa evidência e uma decisão humana registrada. O estado e os gates restantes estão em [operational-readiness.md](docs/operational-readiness.md).

O benchmark v2.13 preserva a v2.11 congelada e avalia ContractFlow e ServiceDesk três vezes em cada política, mantendo os mesmos aliases de modelo. A candidata reduz contexto, schemas, saídas ociosas e retries antes de permitir qualquer roteamento adaptativo. Promoção exige redução real mínima de 40% em tokens/custo sem regressão de schema, isolamento, 17 gates, HRS, testes, cobertura, citações, retries, rework ou avaliação cega dos entregáveis. Sem as runs financiadas, a avaliação fica `blocked`; nunca cria um pass sintético. Veja [learning_layer.md](docs/learning_layer.md).

A baseline v2.11 é carregada de `benchmarks/workflows/software_factory_ai_native_v2_11.yaml` em bancos novos; ela não depende de uma definição histórica já presente no banco. A v2.13 mantém US$ 15 por missão e reservas decrescentes para as etapas críticas. Um teto menor só pode ser decidido após a baseline real.

## Documentação

- [Arquitetura](docs/architecture.md)
- [Segurança e matriz de acesso](docs/security.md)
- [Runbook dos cinco clientes](docs/operations-runbook.md)
- [Ledger](docs/event_ledger.md)
- [Aprendizado curado e benchmark](docs/learning_layer.md)
- [Checklist de homologação](docs/homologation_checklist.md)
- [Deploy VPS](docs/vps_docker_production.md)
