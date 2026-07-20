# Runbook — primeiros 5 clientes assistidos (capacidade técnica de 10 tenants)

## Escopo operacional

O primeiro corte operacional atende cinco clientes conduzidos pelo mesmo operador; a capacidade técnica permanece limitada a 10 tenants, 20 usuários por tenant, 10 workflows concorrentes globais e no máximo 2 por tenant. A stack base opera em `prebuild_only`; o perfil completo habilita `ai_native` somente com provider real, orçamento, Temporal e sandbox Kubernetes. Resposta RAG generativa continua opt-in por cliente. Conectores write-enabled, dados regulados e SLA contratual estão bloqueados.

Metas de continuidade do backup da plataforma: RPO de 24 horas e RTO alvo de 4 horas. Para outputs já confirmados pelo protocolo segmentado, a meta é RPO zero e retomada p95 em até cinco minutos após reinício de API/worker. O ledger nunca é apagado durante reset, restore ou offboarding.

## Subida e verificação

```bash
cp .env.example .env
docker compose up --build
curl --fail http://localhost:8000/live
curl --fail http://localhost:8000/ready
curl --fail http://localhost:8000/health/operational
```

No perfil full/produção, confirme também Prometheus em `:9090`, Grafana em `:3001`, Tempo em `:3200` e o collector OTLP HTTP em `:4318`. Produção bloqueia o startup sem `ASF_OTEL_EXPORTER_OTLP_ENDPOINT`; a stack padrão usa `http://otel-collector:4318/v1/traces`. `local-full-infra-validate.sh` e `vps-docker-validate.sh` publicam um span técnico sem conteúdo e só prosseguem depois de recuperá-lo no Tempo pelo trace ID. Os spans não carregam prompts, respostas, documentos ou código de cliente.

`migrate` usa o papel proprietário `factory`; `db-role-init` cria/atualiza o papel não-superusuário `factory_app`, concede DML e acesso somente à função agregadora `asf_aggregate_technical_metrics()` antes da API. API e worker nunca devem usar o papel proprietário, pois superusuários ignoram RLS. A função de métricas não retorna IDs ou conteúdo tenant-scoped e seu acesso público é revogado. Falha em migration, grants, readiness, OIDC ou banco bloqueia o go-live.

## Onboarding obrigatório

Para o primeiro tenant de uma instalação sem seed, execute uma única vez com o `sub` exato do provedor OIDC:

```bash
docker compose -f docker-compose.vps.yml run --rm migrate python -m app.cli.bootstrap_tenant \
  --tenant-id cliente-inicial --tenant-name 'Cliente Inicial' \
  --subject 'OIDC-SUBJECT' --email owner@example.com \
  --confirm 'bootstrap assisted pilot tenant'
```

O comando usa deliberadamente o papel proprietário do serviço `migrate` para contar tenants através de RLS; ele é uma operação assistida, não uma credencial disponível à API. Em produção, `POST /tenants` e aceite via API ficam bloqueados. O CLI é idempotente e recusa o 11º tenant.

Para os cinco clientes iniciais, execute o mesmo comando cinco vezes, mudando `--tenant-id` e `--tenant-name` e mantendo o mesmo `--subject` do operador. Isso cria cinco memberships separadas e o seletor da UI passa a alternar o tenant efetivo. Use `--enable-rag-generation` somente quando o cliente autorizar que os trechos recuperados sejam enviados ao provedor LLM; sem essa opção, a busca híbrida/extrativa permanece operacional localmente.

1. Criar o tenant; ele nasce em status `onboarding`.
2. Confirmar `storage_prefix=tenants/{tenant_id}/`, workspaces/deliveries fisicamente prefixados por tenant e retenção.
3. Adicionar no máximo 20 usuários e atribuir papéis mínimos.
4. Criar programa e projeto inicial.
5. Criar/confirmar proposta e contrato.
6. Ativar somente os entitlements adquiridos, limites e capabilities.
7. Confirmar `build_mode=ai_native`, provider real, orçamento de US$ 15/run e Generative Build habilitado somente no perfil completo.
8. Executar leitura cross-tenant por ID conhecido e listagem; o resultado precisa ser 404/vazio.
9. Executar um bloqueio de capability não contratada e confirmar 403 no ledger/log.
10. Gerar package AI-native, revisar vínculos de proveniência e registrar aceite.
11. Ativar com `POST /tenants/{id}/onboarding/accept?confirm=accept%20assisted%20pilot%20controls`.

## Ativação do Service Delivery OS

Para cada cliente, siga a ordem abaixo com o tenant correto selecionado na UI:

1. Confirme contrato ativo e entitlement para todas as `component_codes` da oferta.
2. Abra `/engagements`, selecione a versão imutável do catálogo e registre o contexto real do serviço.
3. Gere o plano com IA usando somente knowledge bases autorizadas daquele tenant. Falha de provider ou schema bloqueia; não existe fallback por template.
4. Revise etapas, workstreams, entregáveis, DoD, audiência, riscos e prazos. Aprove o plano explicitamente.
5. Ative o engajamento. A operação materializa a fila e aloca apenas agentes-base previamente homologados; o evento registra a composição inicial.
6. Opere `/work-queue` respeitando cinco itens globais e dois por cliente. Para exceder o limite, informe uma justificativa específica; o ledger registra o override.
7. Produza cada entregável em revisão versionada. Contexto RAG, model call, artifacts e evidências devem pertencer ao tenant ativo.
8. Submeta para decisão humana. Rejeição ou solicitação de ajustes exige comentário; somente uma revisão aprovada pode ser marcada como entregue.
9. Registre baseline, meta e observações em métricas de resultado com unidade, fonte e proveniência `real`, `calculated` ou `estimated`.
10. Antes de trocar de cliente, confirme que não há formulário pendente e use o seletor de tenant. O Cliente 360 faz a troca segura antes de qualquer consulta detalhada.

O catálogo global contém somente as oito definições de serviço. Um banco fresco não pode conter engajamentos, work items, entregáveis, clientes ou candidatos demonstrativos.

## Agent Studio

1. Use os agentes-base aprovados antes de declarar uma lacuna.
2. Registre `agent_gap` somente para uma capacidade de conteúdo/análise ausente. Uma necessidade executável deve ser `tool_gap` e permanece bloqueada.
3. Gere o candidato com o Agent Architect. Revise skill, prompt, schema, política de contexto, ferramentas e orçamento.
4. Execute a avaliação três vezes. Qualquer schema inválido, ferramenta fora da allowlist, orçamento excessivo ou referência cross-tenant impede homologação.
5. Um administrador aprova ou rejeita com comentário. A aprovação cria uma versão imutável privada do tenant.
6. Aloque a versão aprovada ao engajamento e informe apenas knowledge bases do mesmo tenant.
7. Promoção global exige sanitização, nova avaliação e aprovação administrativa independente; código, documentos, IDs e fatos do cliente nunca são promovidos.

## Knowledge e RAG por cliente

1. Selecione o cliente no controle de tenant antes de abrir `/knowledge`.
2. Crie bases exclusivas daquele cliente; nunca use base “compartilhada” para conteúdo comercial ou operacional.
3. Ingerir somente texto/Markdown autorizado, informando título e referência de origem. PDFs/OCR e conectores automáticos ficam fora do primeiro corte.
4. A ingestão gera checksum, chunks recursivos com overlap, índice híbrido versionado, objeto em `tenants/{tenant}/knowledge/{base}/` e evento no ledger sem conteúdo bruto.
5. Faça uma busca por marcador conhecido e confirme que fonte, título e componentes de score aparecem.
6. Repita usando ID conhecido de uma base de outro tenant; o resultado obrigatório é 404/vazio.
7. Mantenha geração LLM desabilitada por padrão. Quando autorizada, registre o consentimento e reprovisione/configure `llm_real=enabled` para aquele tenant.
8. Para substituir documento, ingira a nova versão e arquive a anterior; a operação remove os chunks antigos e preserva a trilha de auditoria.

Bloqueie o cliente se qualquer listagem, consulta, histórico, objeto S3 ou model call contiver referência de outro tenant. Preserve logs e ledger e siga o fluxo de incidente de leakage.

## Jornada padrão

1. Prospect e Opportunity.
2. Briefing, validation e scope MVP/P1/P2.
3. Prebuild comercial AI-native e proposta com pricing determinístico.
4. Aprovação humana com comentário obrigatório.
5. Conversão explícita cria/ativa contrato, entitlement e component instance.
6. ASF Run usa `software_factory_ai_native_v2`; produção agenda via Temporal e executa ferramentas somente em perfis allowlisted no sandbox.
7. Backend tests/smoke, frontend tests/build, Playwright visual, axe e Bandit produzem evidência real; falhas retornam ao Engineer dentro dos limites do YAML.
8. Homologation package é submetido e a aprovação final registra o aceite humano.
9. Delivery passa para `assisted_operation`.

Para `AI Use Case Pilot Sprint`, o engajamento de serviço envolve essa jornada técnica por `rapid_mvp_factory`; o entregável de negócio referencia a run e o homologation package em vez de duplicar suas evidências.

Comandos críticos exigem `Idempotency-Key`. Reuso com payload diferente retorna conflito.

## Operação do executor segmentado

1. Confirme no workspace da run `executor_protocol_version=segmented-output-v1`, `trace_id` e o node atual.
2. O Temporal deve executar `plan_segmented_node` uma vez e `execute_output_unit` sequencialmente para cada unidade. Uma unit concluída precisa ter `output_hash`, `model_call_id`, `finish_reason` e heartbeat.
3. `finish_reason=length` permite no máximo duas continuações e substitui somente a unidade incompleta. Schema inválido permite reparo mínimo; budget/isolamento não repetem.
4. Para artifacts, confirme fragments contíguos e montagem determinística. Para arquivos, confirme `FileChange`/diff e `base_sha256` em patches.
5. Pause e resume pela API de run. Em Temporal, ambos criam commands no outbox e signals `operator_control`; pause só entra em vigor na próxima fronteira segura.
6. Pausa por orçamento deixa a run em `current_phase=budget_paused`. Aumente o envelope de forma autorizada, registre a justificativa e use resume. O signal retoma a unidade; não rebaixe o modelo silenciosamente.
7. Em restart/crash, aguarde até cinco minutos e consulte `GET /runs/{id}/reliability`. Não force uma nova run enquanto a activity idempotente puder reconciliar o checkpoint.
8. Antes da aprovação, confirme 17 gates, HRS mínimo 90, package, hashes e ausência de unit/fragment sem proveniência.

Superfícies de diagnóstico:

- `GET /runs/{id}/execution-units`
- `GET /runs/{id}/reliability`
- `GET /runs/{id}/token-analysis`
- `GET /api/v1/operator/slo`
- `GET /api/v1/admin/platform-readiness`
- `/runtime` e o painel de proveniência da run

Ausência de dados deve aparecer como `insufficient_evidence`, nunca como SLO atendido.

## Readiness e lançamento

`pilot_ready` exige doze execuções comparativas, cinco tenants isolados, ContractFlow e ServiceDesk entregues, cache aquecido com leitura/economia reportadas, recovery comprovado, 17 gates e decisão humana. `market_ready` exige adicionalmente o canário assistido dentro dos SLOs e aprovação do relatório agregado de readiness.

Qualquer exposição cross-tenant, secret, vulnerabilidade crítica, HRS abaixo de 90, missão acima de US$ 15, regressão de retries/rework ou falha de recovery bloqueia promoção. Rollback de learning muda somente o deployment tenant-scoped; rollback de runtime preserva runs históricas e não executa downgrade se existirem runs dependentes das tabelas novas.

## Backup diário

No Compose VPS, jobs separados preservam a cada 24 horas o banco da fábrica, banco do Temporal, banco do Keycloak, `data/api` e o bucket MinIO. Dumps e arquivos locais recebem SHA-256; o espelho MinIO recebe manifesto `SHA256SUMS`. O serviço `backup-offsite` replica tudo a cada cinco minutos para o endpoint S3 externo obrigatório e grava um marcador de sucesso monitorado. A retenção local padrão é de sete dias; a política remota deve ser configurada no bucket externo.

Backup manual:

```bash
docker compose -f docker-compose.vps.yml exec postgres-backup /usr/local/bin/backup-postgres
```

Verificar sempre arquivo `.dump`, `.sha256`, tamanho não zero, timestamp UTC, `asf_backup_newest_age_seconds` para todos os datasets e o objeto correspondente no bucket externo.

## Drill de restore

Nunca testar restore sobre o banco de produção. Use um banco descartável no mesmo Postgres:

```bash
docker compose -f docker-compose.vps.yml exec postgres-backup dropdb --if-exists factory_restore_test
docker compose -f docker-compose.vps.yml exec postgres-backup createdb factory_restore_test
docker compose -f docker-compose.vps.yml exec -e PGDATABASE=factory_restore_test postgres-backup /usr/local/bin/restore-postgres /backups/ARQUIVO.dump
docker compose -f docker-compose.vps.yml exec -e PGDATABASE=factory_restore_test postgres-backup psql -c 'select count(*) from tenants;'
docker compose -f docker-compose.vps.yml exec postgres-backup dropdb factory_restore_test
```

O restore recusa dump sem `.sha256` correspondente ou com checksum divergente. Além do banco principal, o drill deve restaurar em destinos descartáveis os dumps Temporal/Keycloak, o tar de `data/api` e o snapshot MinIO, e então verificar referências de artifacts. Registre início/fim, duração, arquivos, hashes, contagem de tenants e resultado de `verify_hash_chain` por tenant. O drill falha se exceder quatro horas ou se qualquer hash chain/referência for inválida.

## Rotina

Diária: readiness, erros 5xx, jobs/filas, runs travados, aprovações, uso/custos/corpus RAG por tenant, alertas de segurança e último backup.

Semanal: restore em banco descartável, hash chain, rebuild de projeções, acessos negados, gates `review_required`, retrabalho, conversões e packages aprovados.

Mensal: rotação de secrets, revisão de memberships/papéis, tenants inativos, retenção, custos, incidentes e atualização deste runbook.

## Incidente

1. Abrir incidente com horário UTC, tenant, correlação, impacto e severidade.
2. Em suspeita de leakage: suspender tenant/token afetado, bloquear tráfego, preservar logs/ledger e não executar correções destrutivas.
3. Em corrupção de projeção: preservar ledger, validar hash chain e executar rebuild; não editar `ledger_records`.
4. Em falha de banco: interromper mutações, selecionar backup validado e iniciar restore conforme o drill.
5. Comunicar fatos observados separadamente de hipótese/estimativa.
6. Encerrar apenas com causa, evidências, ações, owner e teste de não regressão.

Alertas entregues pelo Alertmanager: API indisponível, respostas 5xx, capacidade esgotada/slot stale, comando Temporal outbox travado e qualquer dataset de backup local/offsite ausente ou com mais de 26 horas. O deploy exige `ASF_ALERT_WEBHOOK_URL`; o go-live exige teste real de disparo e resolução.

## Rotação de credenciais

Rotacionar OIDC client secret, LiteLLM key, LLM provider key, Postgres, MinIO e `ASF_ENCRYPTION_KEY` por procedimento do provedor. Aplicar primeiro em staging, reiniciar serviços dependentes, validar `/ready`, revogar a chave anterior e registrar evento operacional. Nunca colocar valor real em `.env.example`, logs ou tickets.

## Offboarding e exclusão

1. Suspender entitlements e impedir novos runs.
2. Revogar memberships, API keys e sessões OIDC.
3. Exportar artifacts, homologation packages, knowledge autorizado, histórico de queries e ledger conforme retenção contratada.
4. Remover ou criptograficamente inutilizar objetos nos prefixos exclusivos do tenant, incluindo `knowledge/`.
5. Anonimizar dados pessoais quando permitido; preservar ledger mínimo exigido pela política.
6. Marcar tenant como inativo/deleted somente após aprovação dupla e backup final validado.
7. Testar que ID direto, listagem, SSE, artifact, knowledge base e query RAG retornam 404/vazio.
8. Registrar aceite de offboarding e data final de retenção.

Não existe hard delete automático de ledger.

## Rollback de release

1. Bloquear novas mutações e drenar runs.
2. Capturar backup e versão Alembic.
3. Reverter a imagem para a versão anterior.
4. Executar downgrade somente se a migration declarar caminho seguro; caso contrário, restaurar o backup em banco limpo.
5. Validar OIDC, RLS, hash chain, entitlement denial e jornada determinística antes de reabrir.
