# Teste local operacional

## Preparação

Use uma chave de provedor nova e não versionada. Qualquer chave já exposta em conversa, log ou histórico deve ser revogada antes da homologação.

```bash
cp .env.example .env
# substitua os placeholders; a stack base não executa geração técnica
docker compose up --build
```

Serviços base: web `http://localhost:3000`, API `http://localhost:8000`, Keycloak `http://localhost:8081`, LiteLLM `http://localhost:4000`, MinIO `http://localhost:9000` e console MinIO `http://localhost:9001`. Temporal UI `http://localhost:8080` pertence ao perfil full. As portas locais são publicadas apenas em `127.0.0.1`; o nome `localhost` continua válido e a stack não fica exposta na LAN.

O login local usa OIDC Authorization Code + PKCE. O navegador nunca recebe uma credencial em `NEXT_PUBLIC_*` nem exige colar Bearer token. Access e refresh tokens ficam em cookies `HttpOnly`; o BFF encaminha autenticação e tenant à API. O realm local contém `operator@local.dev` (`owner`) e `vp@local.dev` (`engagement_manager`), com as senhas de desenvolvimento declaradas no arquivo de realm. O Compose materializa as duas memberships de modo idempotente. A conta local do VP valida RBAC e jornada sintética, mas não substitui a aprovação do VP real.

`docker compose up` não executa seed. Se um volume anterior ainda contiver registros históricos, preserve-o para auditoria e use um diretório novo sem apagar dados:

```bash
ASF_DATA_ROOT=/tmp/asf-clean docker compose up --build
```

## Cinco clientes

Execute o bootstrap assistido uma vez por tenant, sempre com o `sub` OIDC exato do operador:

```bash
docker compose run --rm local-onboarding python -m app.cli.bootstrap_tenant \
  --tenant-id cliente-01 --tenant-name 'Cliente 01' \
  --subject 'OIDC-SUBJECT-DO-OPERADOR' \
  --confirm 'bootstrap assisted pilot tenant'
```

Repita para `cliente-02` até `cliente-05`. A UI deverá listar exatamente as memberships do operador. Antes de inserir conhecimento ou iniciar missão, confirme o tenant ativo no seletor superior.

## Validação automatizada

```bash
cd apps/api && .venv/bin/pytest -q
cd apps/web && npm run audit:security && npm run build
cd apps/web && npm run test:e2e
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
docker compose config
```

O Playwright autentica owner e VP local no Keycloak pelo PKCE, verifica cookies HttpOnly, recuperação de sessão sem reload, todas as rotas operacionais, guidance e separação de papéis, axe, teclado, reduced motion, breakpoints e uma ingestão/consulta RAG real. `ASF_TEST_COMPLETED_RUN_ID` habilita também o cockpit de uma run contratada já auditada.

### Jornadas narrativas de serviço

A regressão da API inclui um cenário comercial reproduzível para a Vértice
Logística. Ele não altera readiness nem substitui o provider real: usa um
provider determinístico que persiste `ModelCall` e percorre as mesmas funções de
produção usadas pelo worker.

```bash
cd apps/api
uv run pytest tests/test_service_delivery_os.py \
  -k 'realistic_discovery_journey or agentic_deliverable_recovers' -vv
```

O cenário cria contrato e entitlement, gera e aprova um plano de AI Value
Discovery, aloca a equipe curada, produz 11 entregáveis distintos, solicita
ajustes na primeira revisão, produz a revisão seguinte, executa four-eyes nos
19 checks, exporta os formatos editáveis e conclui o engajamento. A variante
triste injeta uma resposta de modelo com schema inválido e comprova retry
durável sem revisão, approval ou artifact duplicado.

Na homologação visual com `ASF_SIMULATE_VP=1`, o primeiro entregável também
passa obrigatoriamente por `Solicitar ajustes → Gerar nova revisão → Submeter
ao VP`. A simulação prova a mecânica e permanece inelegível para liberação
comercial; decisões e evidências reais continuam obrigatórias no corte
liberatório.

Para a infraestrutura production-like completa:

```bash
make docker-doctor
make docker-full-up
make docker-full-validate
```

O perfil completo exige uma chave rotacionada de OpenRouter/OpenAI, aliases `asf-fast`, `asf-reasoning` e `asf-code`, Temporal, MinIO e Kind. Antes da primeira chamada, o simulador exige custo esperado ≤ US$ 15, conservador ≤ US$ 30 e aplica hard stop global de US$ 50. O validador cria ContractFlow e ServiceDesk pelo fluxo contratado, executa os sete perfis allowlisted, confere os 17 gates e compara os fingerprints de código e proposta. As duas runs param em `waiting_for_human`: o validador técnico não as aprova. Seus IDs são entregues à fase `human`, na qual o VP precisa decidir pela interface antes da suíte Playwright estrita.

O saldo do provider deve comportar as duas missões e seus retries auditados. HTTP 402 é bloqueio de homologação, não deve ser contornado reduzindo a saída abaixo do contrato. Modelos `:free` podem ser usados apenas para diagnóstico manual: rate limit 429 ou roteamento sem garantia impede tratá-los como provider operacional.

O cliente confidencial `software-factory-validation` existe somente no perfil de teste para smoke automatizado. Ele não habilita password grant e não substitui o PKCE da interface.

### Carga do portfólio

Para uma sessão OIDC renovável, use o wrapper local. Ele obtém owner e VP pelo
PKCE, mantém access/refresh tokens somente em memória, verifica container e
processos da API antes/depois de cada perfil e publica apenas evidência de um
alvo estável:

```bash
export ASF_TEST_OIDC_USER='<owner OIDC>'
export ASF_TEST_OIDC_PASSWORD='<senha local>'
export ASF_TEST_VP_OIDC_USER='<VP OIDC>'
export ASF_TEST_VP_OIDC_PASSWORD='<senha local>'
export ASF_LOAD_TENANT_ID='<tenant>'
export ASF_LOAD_VP_TENANT_ID='<tenant>'
export ASF_PRODUCTION_E2E_RUN_ID='<id único desta homologação>'
export ASF_LOAD_PROFILES='baseline-2,load-20,load-50,stress-200,spike-500,soak-20'
node apps/web/scripts/run-local-portfolio-load.mjs
```

O `run_id` é persistido nos relatórios de carga, Playwright e restore. O gate
final rejeita arquivos produzidos por outra tentativa, mesmo que estejam verdes
e permaneçam no mesmo diretório.

Também é possível executar um perfil isolado com Bearers temporários. Essa
forma não renova a sessão e, portanto, não deve ser usada para o soak:

```bash
python3 scripts/portfolio-load-test.py --profile baseline-2
python3 scripts/portfolio-load-test.py --profile load-20
python3 scripts/portfolio-load-test.py --profile load-50
python3 scripts/portfolio-load-test.py --profile stress-200
python3 scripts/portfolio-load-test.py --profile spike-500
python3 scripts/portfolio-load-test.py --profile soak-20
```

O harness aquece os endpoints antes da medição, reutiliza uma conexão HTTP por
usuário virtual, aceita somente respostas 2xx, registra reconexões, classifica
timeout de transporte explicitamente, alterna os papéis owner/VP e executa um
comando idempotente duas vezes antes de cada perfil. Configure
`ASF_LOAD_BEARER_TOKEN`, `ASF_LOAD_TENANT_ID`, `ASF_LOAD_VP_BEARER_TOKEN` e
`ASF_LOAD_VP_TENANT_ID`. Os limites são p95 de leitura ≤ 5 segundos, no máximo
5% de erros do provider, 3% de timeout e zero erro inesperado. Reduzir
`--duration-scale` serve apenas para smoke e
não satisfaz homologação. O perfil `soak-20` dura oito horas na escala padrão.
O spike distribui 500 chegadas dentro da janela de 30 segundos e preserva os
últimos 20% da janela em concorrência plena. Relatórios JSON/Markdown são
evidência, mas nunca autoaprovam o próprio gate.

### Gates do primeiro cliente e de produção pública

Depois de concluir as oito ofertas, canário, SLO e validação externa no tenant
de homologação, agregue as evidências sem executar novas mutações:

```bash
export ASF_RELEASE_BEARER_TOKEN='<token temporário do owner>'
export ASF_RELEASE_TENANT_ID='<tenant de homologação>'
export ASF_PRODUCTION_E2E_OUTPUT_DIR="$PWD/artifacts/production-readiness/rodada-final"
make production-e2e-check
```

Para avaliar somente a prontidão do primeiro cliente assistido, sem confundir
esse corte com staging e mercado público, use `make
production-e2e-pilot-check`. Depois de `preflight`, `local`, `human` e `load`,
`make production-e2e-pilot-final` exige todas as evidências internas, a decisão
real do owner e a decisão real do VP. Ele não aceita decisões sintéticas e não
declara `market_ready`.

Para executar a rodada completa, use o mesmo `ASF_PRODUCTION_E2E_RUN_ID` em
todas as fases. Uma credencial nova fica somente no ambiente; nenhum valor é
gravado nos relatórios. O preflight rejeita chave ausente, curta, com
whitespace, prefixo incompatível ou marcador de exemplo antes de qualquer
chamada paga:

```bash
export ASF_PRODUCTION_E2E_CONFIRM=RUN_AUTHORIZED_PRODUCTION_E2E
export ASF_PRODUCTION_E2E_FAULT_CONFIRM=RUN_ISOLATED_FAULT_INJECTION
export ASF_PROVIDER_CREDENTIAL_ROTATED=1
export ASF_PRODUCTION_E2E_COST_CAP_USD=100
export ASF_PRODUCTION_E2E_RUN_ID='candidata-2026-07'
export ASF_TEST_SERVICE_ENGAGEMENT_ID='<engajamento real de homologação>'
export ASF_TEST_OIDC_USER='<owner OIDC>'
export ASF_TEST_OIDC_PASSWORD='<senha obtida do secret store>'
export ASF_TEST_VP_OIDC_USER='<VP OIDC>'
export ASF_TEST_VP_OIDC_PASSWORD='<senha obtida do secret store>'
export ASF_AGENTIC_JOURNEY_EVIDENCE="$PWD/artifacts/production-readiness/candidata-2026-07/agentic-journey-evidence.json"
export ASF_COMMERCIAL_AI_CASE_EVIDENCE="$PWD/artifacts/production-readiness/candidata-2026-07/commercial-ai-case-evidence.json"
make production-e2e-preflight
make production-e2e-local
make production-e2e-human
make production-e2e-load
make production-e2e-pilot-final
```

`pilot-final` e `final` recusam uma rodada sem
`agentic-journey-evidence/1.0`. O arquivo deve reunir uma jornada completa e
duas repetições provider-real do entregável-probe para cada uma das oito
ofertas. A jornada completa contém todos os entregáveis, modos de processo,
model calls, ledger, four-eyes e evidências técnicas; os probes medem
estabilidade com custo controlado. O gate gera
`agentic-journey-evaluation.json`; uma execução isolada, sintética ou
estruturalmente genérica não satisfaz homologação.

Para a candidata 2.1, o gate também exige
`workflow-candidate-evidence/1.0`: três repetições provider-real dos casos
técnicos no workflow histórico 2.13.2 e três no candidato 2.14.0, usando os
mesmos aliases. Contratos e 17 gates devem passar integralmente; nenhum HRS,
segurança ou rastreabilidade pode regredir; a mediana de qualidade não pode
cair e custo/tokens não podem superar 1,2×. O avaliador nunca promove.

O mesmo gate exige `commercial-ai-case-evidence/1.0` para o case canônico
`Opportunity-to-Proposal Copilot`. Os 24 inputs não contêm os rótulos esperados;
o avaliador mantém os rótulos locais, calcula a acurácia de três rodadas
provider-real e bloqueia aprovação automática, ação externa, prompt injection,
ausência de grounding, trilha agentic incompleta, custo/latência fora do limite
ou reutilização de model calls. O relatório é gravado como
`commercial-ai-case-evaluation.json` e continua exigindo decisão humana.

Além das variáveis acima, configure `OPENROUTER_API_KEY` ou `OPENAI_API_KEY`,
`ASF_RELEASE_BEARER_TOKEN`, `ASF_RELEASE_TENANT_ID` e as quatro variáveis de
carga owner/VP. As fases rodam validador full, Playwright estrito, jornada
humana e os perfis `2/20/50/200/500/20-8h` em ordem. O teto da rodada é
validado no preflight e também aplicado pelo gateway de modo global, somando
chamadas de todos os tenants e processos. A fase `local` grava somente os IDs
das duas runs técnicas; a fase `human` exige aprovação real do VP e só então
define a run concluída usada pelo Playwright estrito.
Qualquer falha interrompe a progressão. `ASF_PRODUCTION_E2E_ALLOW_REMOTE=1` só
deve ser usado para um alvo cuja carga foi explicitamente autorizada.

Sem VPS, `make production-e2e-staging` falha explicitamente e o gate de mercado
`final` permanece bloqueado, mesmo que `pilot-final` passe. No ambiente
provisionado, `staging` exige confirmação remota,
`ASF_STAGING_READY=1`, janela de canário ≥ 72 horas e o validador VPS. Somente
depois execute `make production-e2e-final`. O endpoint owner-only
`POST /api/v1/admin/platform-readiness/evaluations` persiste a avaliação
recalculada; ele não promove a versão 2.1.

O validador production-like testa a identidade local do VP provisionada por
`ASF_LOCAL_VP_KEYCLOAK_USER`/`ASF_LOCAL_VP_KEYCLOAK_PASSWORD`. Variáveis de uma
identidade de teste diferente não criam automaticamente um usuário no realm.
Ao final, o validador descreve o namespace Temporal `default`, aguarda o worker
e rejeita traceback de inicialização; o estado `running` isoladamente não é
readiness suficiente.

## Homologação manual

1. Autenticar pelo Keycloak e confirmar que nenhum 401 aparece na interface.
2. Validar os cinco tenants no portfólio sem conteúdo RAG agregado.
3. Em cada tenant, criar/selecionar uma base, indexar um canário exclusivo e confirmar que IDs de outro tenant retornam 404/vazio.
4. Confirmar as oito ofertas, criar um engajamento por contrato, gerar/adaptar o plano com IA e aprová-lo antes da ativação.
5. Validar fila/WIP, equipe AI homologada, revisão do entregável, decisão humana, entrega final e métrica de resultado com fonte/proveniência.
6. Criar uma missão pelo fluxo contratado. Endpoints diretos de run devem responder `409` fora do perfil `test`.
7. Confirmar `software_factory_ai_native_v2`, orçamento, modelo por papel e contexto RAG explicitamente autorizado.
8. Confirmar eventos SSE, papéis/SOPs, artifacts Markdown, `FileChange`, hashes, `model_call_id`, testes, gates, HRS e topologia igual ao YAML.
9. Validar a visão restrita do aprovador e registrar decisão humana idempotente.
10. Confirmar package e entrega promovida, XP ligado ao ledger e nenhuma alteração de gate causada por gamificação.
11. Guardar IDs, logs e packages como evidência; não marcar a missão real como aprovada sem provider válido e teste efetivamente executado.

## Encerramento

```bash
docker compose down
make docker-full-down
```

Não use `down -v` em volumes que contenham evidência ou dados do cliente.
