# Prontidão operacional — cinco clientes assistidos

Atualizado em 2026-07-20. Implementação e evidência são registradas separadamente; nenhum check implica produção autônoma.

## Evidência deste corte

- API local: `108 passed, 16 skipped`; os skips são marcadores explícitos que exigem PostgreSQL/infraestrutura/credenciais production-like ou IDs de runs concluídas. Os testes cobrem catálogo, migrations até `0013`, cinco clientes, isolamento, WIP, entrega, Agent Studio, políticas v2.13, contratos segmentados, execução por unidade, cache provider-aware, learning global, SLOs, patches, retry routing, pausa por orçamento e obrigatoriedade de exportação OTLP em produção.
- PostgreSQL/RLS real: `8 passed` contra o Compose reconstruído usando o papel `factory_app`, incluindo acesso direto cross-tenant negado para knowledge, agente tenant-private, `AIInvocation`, `ExecutionUnit`, `ArtifactFragment` e deployment global; o registro global tenant-free permanece visível e o ledger concorrente/idempotente continua íntegro. O papel restrito vê zero runs sem tenant, mas a função agregadora autorizada retorna métricas técnicas globais sem expor tenant, run ou demanda.
- Web: build Next.js/TypeScript concluído com 32 rotas.
- Compose base e overlay full: configuração renderizada com placeholders não secretos (`--profile full` obrigatório no overlay). O Compose base foi reconstruído, aplicou `0013_aggregate_technical_metrics`, manteve Postgres/MinIO/OIDC e respondeu `live`, `ready`, `health/operational` e `/metrics`; o contrato de banco fresco permanece com 8 ofertas e zero engajamentos, entregáveis e candidatos.
- Observabilidade local: Prometheus e Grafana responderam readiness/health, Collector e Tempo permaneceram ativos, e um span sintético `workflow.run` percorreu SDK → OTLP HTTP → Collector → Tempo e foi recuperado pelo trace ID. Esse smoke agora é bloqueante nos validadores local e VPS e não contém tenant, prompt, artifact ou código.
- Playwright consolidado após rebuild: `5 passed, 1 skipped`, exit code 0. Passaram PKCE/HttpOnly/refresh, rotas sem 401/mocks, catálogo das oito ofertas, axe/teclado/reduced motion/quatro breakpoints e ingestão/consulta RAG em MinIO. O skip exige `ASF_TEST_COMPLETED_RUN_ID` e mantém o cockpit de uma run completa como gate separado.
- O overlay full com Temporal, LiteLLM, secrets obrigatórios e sandbox Kubernetes passa `docker compose --profile full ... config --quiet`; a stack production-like e o cluster de sandbox ainda precisam ser reexecutados com a chave substituta e a versão atual.
- A missão ContractFlow chegou ao Engineer com provider real. Uma chamada concluída com `finish_reason=stop` produziu 26 arquivos/69.825 caracteres, dentro do orçamento de 90.000; o contrato local foi alinhado para aceitar no máximo 32 arquivos sem ampliar o orçamento de conteúdo.
- O retry de provider agora aplica backoff auditável de seis segundos; a tentativa, o intervalo e o `model_call_id` permanecem no ledger. O smoke estruturado confirmou os aliases pagos antes de o saldo acabar.
- A chave exposta permanece configurada apenas no `.env` não versionado por decisão do operador, mas está comprometida e com saldo medido de US$ 0,00. A homologação v2.11 parou no Data Architect com HTTP 402; modelos gratuitos responderam em smoke isolado, porém retornaram 429 sob uso sequencial e não são considerados fallback operacional.

## Implementado

- Command Center dark/pt-BR, sidebar/drawer, tema claro, estados reais, proveniência e cockpit derivado do workflow persistido.
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
- Migrations `0010–0013`, capability registry de modelos, cache provider-aware sem conteúdo de cliente na chave, telemetria de cache reportada, traces OTLP sem prompts, métricas sem label de tenant e APIs de execution units/reliability/SLO/readiness. A stack full provisiona Collector, Tempo e datasources Grafana; a agregação cross-tenant do Prometheus ocorre somente por função owner-executed com busca fixada, acesso público revogado e payload sem identificadores/conteúdo.
- Registro global tenant-free somente para padrões sanitizados, deployments tenant-scoped com RLS, precedência fixa, promoção administrativa e rollback de ponteiro. A UI separa learning privado, global e efetivo.
- Análise operacional de custo por tenant/jornada/operação/agente/modelo/política e auditoria por invocação sem prompts, respostas ou chain-of-thought. A interface separa custo real, custo projetado, cache reportado, retries e referências citadas.
- Navegação operacional reorganizada em Carteira, Serviços, Execução, Equipe AI, Operações técnicas e Administração; o conteúdo detalhado só é consultado depois da seleção segura do tenant.

## Gates restantes

- [ ] Revogar a chave de provider exposta, configurar uma substituta apenas em secret/env não versionado e garantir saldo suficiente para as duas missões (o saldo atual é zero).
- [ ] Provisionar os cinco tenants/memberships reais em um volume operacional limpo; o volume local atual contém dados de desenvolvimento/E2E e nenhuma run v2 concluída.
- [x] Concluir a suíte Playwright consolidada sem falhas (`5 passed, 1 skipped` condicional ao ID de run).
- [ ] Executar ContractFlow e ServiceDesk reais em `software_factory_ai_native_v2` após a rotação da chave, com artifacts, diffs, sete perfis de sandbox, 17 gates, aprovação e entrega.
- [ ] Comprovar em Temporal real pause/resume, budget resume e restart do worker durante model call, unidade, sandbox e espera humana; os contratos e activities estão implementados, mas o crash drill production-like ainda não foi executado.
- [ ] Executar restore em ambiente limpo e medir RPO/RTO; validar backup offsite e alertas reais.
- [ ] Validar sandbox/PVC/NetworkPolicy no cluster de destino e chamadas MCP negadas auditadas.
- [ ] Guardar os dois validation manifests e confirmar custo real total de cada missão abaixo de US$ 15.
- [ ] Executar a baseline v2.11 e a candidata v2.13 três vezes para ContractFlow e ServiceDesk com aliases idênticos; comprovar redução mediana mínima de 40% e qualidade cega não inferior antes de promover a política.

## Linha de corte

O código está preparado para continuar a homologação local AI-native e para o piloto assistido de cinco clientes, com isolamento explícito e um operador humano. Ainda não há evidência de missão técnica concluída: o saldo do provider interrompeu ContractFlow antes do sandbox, gates e aprovação, e ServiceDesk não foi iniciada. A liberação operacional depende de uma chave válida com saldo, rotação da credencial exposta e `make docker-full-validate` concluído sem skip/falha. Não está autorizado como serviço autônomo exposto à internet.
