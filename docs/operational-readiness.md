# Prontidão operacional — cinco clientes assistidos

## Homologação visível, assistida por operadores

A jornada comercial real pode ser acompanhada em um Chromium visível com vídeo local:

```bash
cd apps/web
ASF_INTERACTIVE_HOMOLOGATION=1 \
ASF_TEST_SERVICE_ENGAGEMENT_ID=<engagement-id> \
ASF_TEST_CONTRACTFLOW_RUN_ID=<contractflow-run-id> \
ASF_TEST_SERVICEDESK_RUN_ID=<servicedesk-run-id> \
ASF_TEST_VP_OIDC_USER=<vp-user> \
ASF_TEST_VP_OIDC_PASSWORD=<vp-password> \
npm run test:e2e:homologation
```

O Playwright autentica owner e VP em contextos temporários sem vídeo, transfere
somente o estado de sessão em memória e inicia dois contextos isolados gravados.
Ele começa pelas decisões reais do VP sobre ContractFlow e ServiceDesk e só
depois executa as ações operacionais do owner, materializa o plano e enfileira
os work items. Aprovação das duas runs técnicas, aprovação de plano, evidência humana,
aprovação/entrega de cada entregável e decisões do Definition of Done não são
automatizadas: a janela para no gate correspondente e aguarda a pessoa
autorizada. Vídeos e trace de falha começam somente após o login e ficam em
`apps/web/test-results/homologation-visible`.

Para a homologação real, com ritmo lento e confirmação visual entre marcos,
execute (o default é `ASF_SIMULATE_VP=0`):

```bash
bash scripts/run-visible-homologation.sh
```

Para uma repetição funcional não liberatória, defina explicitamente
`ASF_SIMULATE_VP=1`; esse modo grava `SIMULAÇÃO DE HOMOLOGAÇÃO` em todas as
decisões. A jornada
tem limite global de 90 minutos, esperas e polling são limitados e nenhum ZIP
comercial é liberado por decisão sintética. Plano, run técnico, gate humano,
entregável, entrega e checks recebem estados `synthetic_*`; por isso não podem
promover o catálogo, concluir o engajamento real ou alimentar aprendizado global.
Essa repetição agora inclui um ciclo visível de retrabalho: o VP solicita
ajustes na primeira revisão, o owner orienta a correção agentic, uma nova
revisão é persistida e somente então o material volta para decisão.

Em paralelo, a suíte da API possui uma jornada narrativa determinística que
conclui um AI Value Discovery realista com 11 entregáveis diferentes, 19 checks
four-eyes e pacotes editáveis. Ela também injeta schema inválido no provider e
prova recuperação sem artifact duplicado. Esse teste protege a lógica de
produção a cada commit, mas não é evidência de provider externo nem concede
readiness.

## Interface orientada à próxima ação

- Owner inicia em **Hoje**; VP inicia em **Minha fila**. O menu técnico foi
  agrupado em **Diagnóstico**, mantendo todas as URLs históricas por deep link.
- Engajamentos seguem `Plano → Aprovação → Execução → Entregáveis → Aceite e
  entrega`; detalhes técnicos ficam em expansão progressiva.
- `OperationalGuidance` combina uma ação calculada pelo servidor com narrativa
  limitada do modelo. O modelo nunca fornece `kind`, `href`, `resource_id`,
  prioridade, responsável, estado ou autoridade.
- A explicação de IA é solicitada apenas junto da geração de plano ou entregável
  já necessária e fica vinculada a `ModelCall`, ledger, `AIActivity` e
  `AgentRecommendation`. Refresh e navegação recompõem a projeção sem chamar o
  provider. Mudança de versão, execução, revisão, entregável ou check altera o
  `state_hash` e invalida a orientação anterior.
- Sem provider, a orientação usa fallback determinístico. GETs e sessão expiram
  em 15 segundos; comandos em 120 segundos; o BFF adiciona cinco segundos e
  devolve `504 UPSTREAM_TIMEOUT` com correlation ID. Um comando expirado fica
  com resultado não confirmado e exige refresh antes de nova submissão.
- Falhas de sessão e de recurso exibem retry sem reload. Dados já carregados são
  preservados durante refresh e perda de SSE aparece como “Atualizações
  pausadas”.

Atualizado em 2026-07-23. Implementação e evidência são registradas separadamente; nenhum check implica produção autônoma.

### Atualização de homologação em 2026-07-28

A rodada `first-client-20260728` substitui os números operacionais abaixo para
o corte mais recente:

- API local: 179 testes coletados, 161 aprovados e 18 cenários externos
  deliberadamente pulados. No Compose production-like, uma base PostgreSQL
  descartável foi migrada de `0001` a `0017` e executou 176 testes aprovados,
  com três cenários externos pulados.
- Uma reinicialização do Temporal revelou duas runs antigas com workflow
  ausente e lease expirada. A reconciliação passou a considerar `NOT_FOUND`
  terminal, o comando de cancelamento pendente pode ser reenfileirado
  idempotentemente, as duas runs chegaram a `cancelled` e os dois slots foram
  liberados sem edição direta do banco.
- Web em Next.js `16.2.12`, PostCSS `8.5.24` e `brace-expansion 5.0.8`:
  TypeScript/build de 33 rotas e `npm audit` com zero vulnerabilidade conhecida.
- Playwright autenticado: 11/11, sem skip, flake ou falha. Owner, VP,
  catálogo das oito ofertas, fluxo de engajamento, cockpit de run, RAG,
  acessibilidade, responsividade, timeout e retry foram exercitados.
- Backup/restore: três restores, RPO zero, RTO p95 de `0,009 s`, hash-chain
  válida e rejeição tanto do dump adulterado quanto do ledger adulterado.
- Carga: `2/20/50/200/500` passaram com 110, 1.101, 1.820, 4.148 e 2.027
  requisições; todos tiveram zero falha, zero timeout e zero erro inesperado.
  Os p95 foram `157 ms`, `252 ms`, `207 ms`, `786 ms` e `35 ms`.
  Cada relatório comprova que o container e seus quatro workers permaneceram
  estáveis durante o perfil. O Docker Desktop reiniciou entre o stress e o
  spike, portanto a sequência integral ainda deve ser repetida no host de
  homologação; o limite local é 8 CPU, 8 GiB no macOS e 4 GiB na VM Docker.
- O fault provider determinístico validou `429`, `503`, timeout, conexão
  interrompida, JSON truncado e schema inválido. O gate agora aguarda o
  healthcheck do provider antes de iniciar a injeção, eliminando uma corrida de
  startup observada nesta rodada.
- O `check` autenticado permaneceu corretamente vermelho. API, custo,
  Playwright e restore estão verdes; faltam o soak real de oito horas, as oito
  ofertas e dois ciclos do AI Office concluídos, os relatórios obrigatórios e
  decisões distintas de owner/VP. A stack usou provider deliberadamente inerte
  e nenhuma credencial exposta foi reutilizada.

Evidências locais: `artifacts/production-readiness/first-client-20260728/`.

### Validação do código do gate em 2026-07-23

- API completa: `159 passed, 18 skipped`; os 18 casos externos continuam
  fora da contagem de liberação.
- API focada em evidência/readiness/provider: `48 passed`.
- Scripts do gate/carga/restore: `19 passed`.
- TypeScript sem emissão e build Next.js: verdes, com 33 rotas.
- Compose base, full, fault-injection e VPS: configuração válida usando somente
  placeholders não secretos.
- O `check` autenticado de `internal_assisted_pilot_ready` confirmou API,
  custo, Playwright e backup/restore verdes. Ele permanece vermelho porque o
  soak de oito horas não existe, nenhuma das oito ofertas possui entrega real
  aceita, os relatórios internos obrigatórios não passaram e ainda não há
  evidência distinta de owner/VP. A avaliação persistida continua corretamente
  como `blocked`.

**Veredito do corte:** candidata funcional para operação interna assistida, mas
**ainda não pronta para receber o primeiro cliente**. A jornada autenticada e
os perfis `2/20/50/200/500` passaram contra um alvo estável. O soak de oito
horas ainda não foi executado. A credencial de provider compartilhada
anteriormente não foi reutilizada nesta rodada.

## Evidência deste corte

- API em banco PostgreSQL descartável migrado de `0001` a `0017`: `160 passed, 3 skipped` em `136,67 s`. Os skips exigem jornadas externas/IDs de runs concluídas e não foram contabilizados como sucesso. A suíte emitiu `11.797` avisos de datetime ingênuo; não causaram falha, mas permanecem como dívida antes de endurecer o runtime.
- PostgreSQL/RLS real: `8 passed` contra o Compose reconstruído usando o papel `factory_app`, incluindo acesso direto cross-tenant negado para knowledge, agente tenant-private, `AIInvocation`, `ExecutionUnit`, `ArtifactFragment` e deployment global; o registro global tenant-free permanece visível e o ledger concorrente/idempotente continua íntegro. O papel restrito vê zero runs sem tenant, mas a função agregadora autorizada retorna métricas técnicas globais sem expor tenant, run ou demanda.
- Web: TypeScript e build de produção Next.js `16.2.11` concluídos com 33 rotas. A auditoria npm completa e somente de produção retornou zero vulnerabilidades conhecidas após fixar `sharp 0.35.3` e `js-yaml 4.3.0`.
- Imagens `api`, `web` e `temporal-worker` reconstruídas com sucesso após a integração v2.13.2; API permaneceu saudável e o worker permaneceu ativo no perfil local `homologation + litellm + temporal`. `docker compose config --quiet` passou para base, full e VPS com placeholders não secretos.
- Compose base e overlay full: configuração renderizada com placeholders não secretos (`--profile full` obrigatório no overlay). O Compose base foi reconstruído, aplicou `0013_aggregate_technical_metrics`, manteve Postgres/MinIO/OIDC e respondeu `live`, `ready`, `health/operational` e `/metrics`; o contrato de banco fresco permanece com 8 ofertas e zero engajamentos, entregáveis e candidatos.
- Observabilidade local: Prometheus e Grafana responderam readiness/health, Collector e Tempo permaneceram ativos, e um span sintético `workflow.run` percorreu SDK → OTLP HTTP → Collector → Tempo e foi recuperado pelo trace ID. Esse smoke agora é bloqueante nos validadores local e VPS e não contém tenant, prompt, artifact ou código.
- Playwright de release autenticado: `10 passed, 1 skipped`, contra
  Web/API/Keycloak reais. A suíte validou OIDC/PKCE, timeout e retry de sessão
  sem reload, todas as rotas operacionais, as oito ofertas,
  acessibilidade/responsividade, RAG tenant-scoped, owner/VP e decisão de
  entregável. O único skip é deliberadamente bloqueante: não existe neste corte
  uma run AI-native contratada, concluída e auditada para validar o cockpit.
- Compose base, full e VPS passaram `config --quiet` com placeholders não secretos. O smoke de observabilidade persistiu e recuperou um trace Collector → Tempo. O teste pós-E2E detectou Temporal sem o schema `namespaces`; o serviço isolado foi reinicializado, o namespace `default` foi descrito pela CLI e o worker permaneceu ativo sem traceback. O validador agora trata namespace e estabilidade do worker como gates, em vez de aceitar apenas o estado `running` do container.
- Backup/restore local production-like: três restores descartáveis passaram com RPO zero para outputs confirmados, hash-chain válida e RTO p95 de aproximadamente `0,002 s`. O drill provou que o trigger append-only rejeita mutação e que dump com SHA-256 divergente e ledger adulterado são rejeitados. Backup offsite continua pendente.
- Carga fail-closed: a série limpa de 2, 20, 50 e 200 usuários passou no
  mesmo alvo estável com 112, 1.120, 1.842 e 3.895 requests, zero
  falha/timeout e p95 de `0,181 s`, `0,222 s`, `0,082 s` e `2,542 s`.
  O spike distribuído de 500 usuários passou com 2.032 requests, zero
  falha/timeout, p95 de `0,328 s` e o mesmo hash de container/processos antes e
  depois. Temporal worker, LiteLLM e Kind permaneceram desligados durante a
  série para isolar a capacidade HTTP da API; após o teste, os três foram
  restaurados. LiteLLM levou aproximadamente cinco minutos para ficar pronto no
  Docker local limitado a 3,8 GiB, enquanto o nó Kind voltou `Ready`. Portanto,
  esta evidência não substitui carga concorrente da stack completa na
  infraestrutura mínima de produção. O soak de 20 usuários/8 h ainda não foi
  executado.
- A stack production-like desta rodada usou provider deliberadamente inerte. Nenhuma chamada externa foi feita com a credencial exposta; as oito ofertas e as duas missões técnicas reais ainda exigem uma credencial substituta, saldo e aprovação humana.
- A missão ContractFlow chegou ao Engineer com provider real. Uma chamada concluída com `finish_reason=stop` produziu 26 arquivos/69.825 caracteres, dentro do orçamento de 90.000; o contrato local foi alinhado para aceitar no máximo 32 arquivos sem ampliar o orçamento de conteúdo.
- O retry de provider agora aplica backoff auditável de seis segundos; a tentativa, o intervalo e o `model_call_id` permanecem no ledger. O smoke estruturado confirmou os aliases pagos antes de o saldo acabar.
- A credencial fornecida permanece apenas em arquivos locais ignorados, com permissões restritas, e não aparece no diff versionável. Ela concluiu o planejamento real do case pela rota API → LiteLLM → OpenRouter, com uso e custo persistidos. Como foi compartilhada em conversa, continua comprometida para fins de produção e deve ser rotacionada antes de qualquer liberação externa.

## Implementado

- Homes **Hoje** e **Minha fila** por papel, sidebar/drawer, tema claro, guidance com proveniência e cockpit derivado do workflow persistido.
- OIDC PKCE com BFF, cookies HttpOnly, refresh central e RBAC server-side. O prefetch acidental do endpoint de logout foi eliminado.
- Portfolio e overview tenant-scoped, workspace de run, topologia YAML, projeção segura de review e decisões idempotentes.
- `audience` em artifacts; somente artifacts promovidos saem pela API do reviewer.
- Gamificação auditável com unicidade por tenant/ledger/evento/beneficiário e sem efeito em HRS, gates ou autorização.
- Seed e AFlow stub removidos dos perfis operacionais. Batches exigem nome e IDs persistidos; runs diretas são exclusivas de testes.
- Provider real obrigatório fora de `test`; custo só é exibido quando derivado de resposta real precificada.
- RAG, storage e ledger isolados por tenant com RLS e testes de cinco clientes.
- Workflow `software_factory_ai_native_v2` v2.11, executor genérico YAML, `ContextBundle`, `AgentStepResult`, `AgentStepExecution`, routing por papel, US$ 15/run, retry com backoff no ledger, geração inicial limitada a 32 arquivos/90.000 caracteres, loops observados por testes e sete perfis de sandbox.
- Cockpit exibe custo, chamadas, hashes, steps, invariantes e fingerprint sem expor esse conteúdo ao reviewer.
- Validador local está configurado para duas missões reais diferentes (ContractFlow e ServiceDesk) e rejeita código/proposta equivalentes ou evidência incompleta.
- Service Delivery OS com oito ofertas versionadas, Cliente 360, engajamentos, planos AI com aprovação, fila/WIP 5 global e 2 por tenant, entregáveis de negócio, revisões, decisão, entrega e métricas de resultado com proveniência.
- Agent Studio tenant-private com oito agentes-base, composição inicial por oferta, lacunas de capacidade, tool gaps bloqueados, candidato AI, três avaliações e versão imutável somente após homologação humana.
- Política v2.13 imutável com `AIInvocation`, envelopes por operação, atribuição de tentativas, contexto por papel/seção, digests privados por checksum, contratos Pydantic por papel, patches com `base_sha256` e retries classificados.
- Protocolo `segmented-output-v1` com plano curto, até 32 unidades, até 12 seções/artifact, quatro arquivos/lote, model call e heartbeat por unidade, fragments imutáveis e montagem determinística. Temporal usa activities reais de planejamento/unidade/montagem; replay mantém hashes e não duplica artifacts/events.
- Migrations `0010–0017`, capability registry de modelos, cache provider-aware sem conteúdo de cliente na chave, telemetria de cache reportada, contexto compacto auditável por unidade, traces OTLP sem prompts, métricas sem label de tenant e APIs de execution units/reliability/SLO/readiness. A stack full provisiona Collector, Tempo e datasources Grafana; a agregação cross-tenant do Prometheus ocorre somente por função owner-executed com busca fixada, acesso público revogado e payload sem identificadores/conteúdo.
- Política v2.13.2 selecionada como default de novas runs por decisão do operador, com Ponytail canônico 4.8.4 e Cavekit 4.1.0 fixados por revisão, cobertura integral de comandos, invocações tenant-scoped/eventos, artifacts `PONYTAIL_AUDIT.md`/`PONYTAIL_DEBT.md` e gate de rastreabilidade exata entre requisito, critério, invariante, arquivo, teste e relatório allowlisted aprovado. Os adaptadores não executam código upstream nem recebem shell, secrets ou autoridade sobre gates; rollout externo continua condicionado ao benchmark.
- Lifecycle Cavekit fail-closed: ativações começam `registered`, conclusão exige evidência persistida, backprop usa relatórios reais do sandbox, deepen usa gates avaliados e o validation manifest rejeita estágio pendente, evidência ausente ou falha sem recuperação.
- Registro global tenant-free somente para padrões sanitizados, deployments tenant-scoped com RLS, precedência fixa, promoção administrativa e rollback de ponteiro. A UI separa learning privado, global e efetivo.
- Análise operacional de custo por tenant/jornada/operação/agente/modelo/política e auditoria por invocação sem prompts, respostas ou chain-of-thought. A interface separa custo real, custo projetado, cache reportado, retries e referências citadas.
- Navegação owner reorganizada em Hoje, Clientes, Serviços, Operação e Entregas; navegação VP em Minha fila, Engajamentos, Entregas e Evidências. Operações técnicas e telas históricas ficam em Diagnóstico sem remover deep links.

## Portfólio 2.0 — estado da candidata

- As oito ofertas estão definidas em catálogo canônico versionado, mantendo a apresentação histórica da versão `1.0` e `AI Use Case Pilot` apenas na `2.0`.
- A ativação materializa equipe curada, etapas classificadas, work items, entregáveis estruturados, dependências e checks específicos/corporativos tenant-scoped. Testes cobrem materialização e isolamento das estruturas.
- A execução durável usa outbox, scheduler round-robin e Temporal, com WIP de cinco itens globais/dois por tenant e dez workflows AI-native globais/dois por tenant. O teste automatizado comprova distribuição `2/2/1` entre três tenants e deixa o sexto item enfileirado.
- Cancelamento prevalece sobre retorno tardio do provider, checkpoints e heartbeat são persistidos, e retry/cancel mantêm idempotência, versão e ledger append-only.
- O AI Office exige comando humano para cada novo ciclo; a homologação requer dois ciclos consecutivos aceitos.
- Four-eyes foi aplicado: aprovação de plano, decisões de aceite, exceções externas e entrega final pertencem ao `engagement_manager`; owner mantém configuração, execução, recovery e incidentes.
- A fila do VP segue `Plano → Qualidade → Entregáveis → Entrega`; entregáveis são decididos somente pelo endpoint especializado, com comentário obrigatório, evitando divergência entre aprovação, revisão, status operacional e ledger.
- Pacotes finais incluem manifesto e fontes/editáveis em Markdown, JSON, CSV, DOCX, PPTX, XLSX e ZIP, com SHA-256, MIME, tamanho, origem e versão persistidos.
- O catálogo só pode ser promovido após evidências persistidas dos oito serviços, catálogo, onda multi-serviço, carga, resiliência, usabilidade dos dois operadores, backup/restore, sandbox e formatos editáveis. O código não autoaprova relatórios nem libera `market_ready`.
- O harness `scripts/portfolio-load-test.py` possui perfis de 2, 20, 50, 200 e 500 usuários e soak de 20 por oito horas. Ele mistura leituras de owner/VP, mede p95, prova idempotência com uma fixture dedicada, reutiliza conexões por usuário virtual e gera Markdown/JSON sem aprovar a própria evidência. O wrapper local renova OIDC apenas em memória e só publica o relatório quando container e processos da API permanecem estáveis.
- O gate de produção é retomável por `run_id` nas fases `preflight`, `local`, `human`, `load`, `pilot-final`, `staging` e `final`. `pilot-final` avalia explicitamente `internal_assisted_pilot_ready` sem exigir os gates de mercado público; `final` continua exigindo staging, canário e `market_ready`. Cada fase grava um marcador com hash somente depois de passar; `check` não altera a aplicação. Chamadas pagas, fault injection e alvo remoto possuem confirmações independentes. ContractFlow e ServiceDesk param no gate humano; a fase `human` exige decisão real pela UI antes de executar o Playwright sem skips.
- `pilot-final` e `final` também exigem uma jornada completa e duas repetições provider-real do entregável-probe para cada uma das oito ofertas em `agentic-journey-evidence/1.0`. O avaliador confere cobertura de templates e modos, especificidade do cliente, claims e referências verificadas, ausência de alegações proibidas, diversidade entre entregáveis, trilha dos agentes, avaliação do sistema de IA em qualidade/grounding/segurança/controle humano/latência/custo, four-eyes, eventos terminais e, quando aplicável, 17 gates, HRS ≥ 90 e Ponytail/Cavekit terminais. O relatório não promove nem aprova a versão.
- O case canônico `Opportunity-to-Proposal Copilot` possui um gate independente em `commercial-ai-case-evidence/1.0`: 24 inputs com rótulos held-out, oito ataques, três rodadas provider-real, acurácia mínima de 90%, rastreabilidade integral dos model calls, limites de custo/latência/erro e decisão identificada do VP. O gate deriva os resultados e recusa evidência sintética ou rótulos expostos aos agentes.
- A matriz operacional também exige que um Discovery documental e um MVP técnico de IA sejam vendáveis e executáveis separadamente ou em paralelo. O MVP não termina sem código, diffs completos, test reports, 17 gates, HRS ≥ 90, plugins terminais e hash do pacote; o Discovery não é artificialmente transformado em desenvolvimento de software.
- Evidência v2 usa manifesto tipado, SHA-256 e referências tenant-scoped. O servidor deriva `passed`; `status` enviado pelo cliente é apenas compatibilidade de transporte. A avaliação owner-only de prontidão persiste um snapshot recalculado e nunca promove o catálogo.
- O drill local faz três restores descartáveis, compara artifacts, ledger, chamadas de modelo, entregáveis confirmados e runs aprovadas, mede RTO incluindo verificação, exige RPO zero e prova que tanto um dump com hash divergente quanto um ledger restaurado adulterado são rejeitados.

Status atual: `candidate`. A jornada funcional automatizada, o build, a auditoria de dependências, o restore local, o fault provider e os perfis `2/20/50/200/500` possuem evidência verde contra um alvo estável. O soak de oito horas foi iniciado em 2026-07-30 e só contará depois de completar sua duração integral. `internal_assisted_pilot_ready` permanece bloqueado pela execução real das ofertas contratadas, sandbox terminal, run técnica auditada e as duas sessões humanas. `market_ready` permanece adicionalmente bloqueado por canário real, SLO operacional e validação com usuários externos.

### Atualização de evidência em 2026-07-30

- API completa e 34 testes dos avaliadores, mais quatro subtestes, terminaram com
  código zero. O build de produção compilou, validou TypeScript e gerou 33
  rotas.
- A stack atual foi reconstruída com quatro workers Uvicorn. O Playwright de
  release passou 10 de 11 cenários em 60 segundos; o único skip continua sendo
  bloqueante e corresponde ao cockpit de uma run AI-native contratada,
  concluída e auditada, que ainda não existe no volume atual.
- Em uma única instância estável, os perfis integrais `2/20/50/200/500`
  passaram com 116, 1.126, 1.839, 4.288 e 2.028 requisições. Todos tiveram zero
  timeout e zero erro; os p95 foram 64, 189, 74, 86 e 35 ms. O contêiner
  permaneceu saudável, com `RestartCount=0` e os mesmos quatro processos antes
  e depois de cada perfil.
- O fault provider em runtime comprovou `429`, `503`, timeout, resposta
  truncada, schema inválido e conexão interrompida; os testes de gateway
  associados passaram.
- O drill repetiu três restores com RPO zero, ledger íntegro e antitamper
  ativo. O medidor agora rejeita amostras negativas e normaliza apenas ruído
  submicrossegundo do relógio monotônico; o RTO p95 observado foi 0,005 s.
- O snapshot somente leitura está em
  `artifacts/production-readiness/local-unpaid/final/`. Ele mantém a candidata
  vermelha por ausência de credenciais rotacionadas, avaliação persistida,
  provider real, run concluída sem skip, soak concluído e decisões humanas.

O primeiro caso real foi especificado em 2026-07-21: `Opportunity-to-Proposal Copilot`, uma operação interna do owner e do VP contratada como `AI Use Case Pilot 2.0`. Bundle, dataset held-out de 24 cenários, oito ataques, rubrica, runner API e avaliador AI-native estão prontos. O provider real gerou e persistiu o plano v1. O volume local atual contém o engajamento `active`, seis workstreams, 13 entregáveis, 13 itens e 13 execuções: duas aguardam revisão, duas estão delegadas e nove estão enfileiradas. A interface confirmou a separação owner/VP e o guidance contextual, mas Temporal, sandbox, 17 gates, três rodadas de avaliação, revisão integral, aceite humano e entrega ainda não terminaram; portanto o case não constitui homologação concluída.

Atualização de 2026-07-23: o plano da instância ativa possui uma decisão
explicitamente sintética e não pode ser usado como aceite comercial do VP. A
suíte Playwright estrita passou `10/11`; o cockpit foi corretamente pulado
porque não há uma run AI-native concluída e auditada neste corte. Uma nova
instância `vp-demo-20260723` foi criada em `draft` para preservar o histórico e
receber a decisão pessoal do VP. A geração do novo plano permanece bloqueada até
a rotação da credencial já exposta. O gate dessa rodada está em
`artifacts/production-readiness/vp-demo-20260723/final`.

## Gates restantes

- [ ] Revogar a chave de provider exposta, configurar uma substituta apenas em secret/env não versionado e garantir saldo suficiente para as duas missões (o saldo atual é zero).
- [ ] Provisionar os cinco tenants/memberships reais em um volume operacional limpo; o volume local atual contém dados de desenvolvimento/E2E e nenhuma run v2 concluída.
- [ ] Reexecutar a suíte Playwright de release com Web/API/OIDC ativos e uma
  run AI-native concluída deste corte (`10 passed, 1 skipped` atualmente).
- [x] Compilar a v2.13.2 e validar deterministicamente os 18 papéis e nove estágios Cavekit sem ativações pendentes, com evidência e recuperação auditável (`test_all_v2132_roles_finish_every_cavekit_stage_with_persisted_evidence`).
- [ ] Executar ContractFlow e ServiceDesk reais em `software_factory_ai_native_v2` após a rotação da chave, com artifacts, diffs, sete perfis de sandbox, 17 gates, aprovação e entrega.
- [ ] Comprovar em Temporal real pause/resume, budget resume e restart do worker durante model call, unidade, sandbox e espera humana; os contratos e activities estão implementados, mas o crash drill production-like ainda não foi executado.
- [x] Executar restore local em três bancos descartáveis, medir RPO/RTO e validar integridade/antitamper do ledger.
- [ ] Validar backup offsite e alertas reais no ambiente de destino.
- [ ] Validar sandbox/PVC/NetworkPolicy no cluster de destino e chamadas MCP negadas auditadas.
- [x] Reexecutar a suíte PostgreSQL/RLS com a migration `0015`, incluindo invisibilidade cross-tenant de `PluginInvocation` (`8 passed` em 2026-07-20 com `factory_app` sem bypass).
- [ ] Guardar os dois validation manifests e confirmar custo real total de cada missão abaixo de US$ 15.
- [ ] Executar a baseline v2.11 e a candidata v2.13 três vezes para ContractFlow e ServiceDesk com aliases idênticos; comprovar redução mediana mínima de 40% e qualidade cega não inferior antes de promover a política.
- [ ] Executar v2.13.1 primeiro em shadow/interno e comparar source/sent tokens por unidade, cache real, retries, rework, HRS e avaliação cega; somente então alterar `ASF_AI_NATIVE_POLICY_VERSION` nos tenants canários.
- [ ] Executar v2.13.2 em shadow sobre as mesmas missões/aliases, validar que todos os comandos Ponytail/Cavekit terminaram em `completed|not_applicable`, comparar complexidade/dependências/rework e obter decisão humana antes de qualquer rollout para cliente.
- [ ] Homologar as oito ofertas 2.0 ponta a ponta com provider real, formatos editáveis, checks específicos/corporativos, apresentação, handover, decisão do VP e pacote final.
- [ ] Executar a onda multi-serviço A=`2`, B=`2`, C=`1`, comprovar o sexto item enfileirado em runtime real e validar reuso same-tenant sem vazamento cross-tenant.
- [x] Repetir em uma única série estável os perfis `2/20/50/200` e preservar o spike `500` verde.
- [ ] Executar soak `20` por oito horas e aprovar os relatórios sem autoaceite.
- [ ] Executar duas rodadas de usabilidade: owner para operação/recovery e VP para negócio/aprovação/entrega, com 100% das tarefas críticas, zero P0/P1 e SEQ mediano mínimo de 5/7.

## Linha de corte

O código e a interface estão preparados para continuar a homologação local AI-native e o piloto assistido. O E2E funcional e os perfis `2/20/50/200/500` estão verdes, mas falta o soak de oito horas e não existe evidência nova de missão técnica real concluída: faltam provider substituto, sandbox terminal, 17 gates, artifacts, checks, aceite pessoal do VP e entrega. A liberação depende dessas evidências e da validação sem skips relevantes. Não está autorizado como serviço autônomo exposto à internet.
