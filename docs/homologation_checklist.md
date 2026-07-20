# Checklist de homologação

## Automatizado

- [x] Banco fresco inicia sem tenant, cliente, projeto, crédito, run, agent ou histórico demonstrativo.
- [x] API cobre cinco tenants, RLS/RAG, artifacts, review, papéis, topologia e XP idempotente.
- [x] Next.js compila as 28 rotas e os tipos são gerados do OpenAPI.
- [x] Compose base e VPS passam em `config` com configuração válida.
- [x] Migration fresca `0006_ai_native_workflow_v2` passa upgrade e downgrade.
- [x] Playwright consolidado passa PKCE, refresh, menus, ações, zero-mock, axe, teclado, reduced motion e quatro breakpoints (`4 passed, 1 skipped`).
- [ ] Playwright do cockpit passa com `ASF_TEST_COMPLETED_RUN_ID` de uma run contratada deste corte.

## Segurança e dados

- [x] Tokens ficam fora do DOM e dos storages; BFF encaminha bearer/tenant.
- [x] Endpoints técnicos e administrativos aplicam RBAC no servidor.
- [x] Reviewer não recebe logs, prompts, custos internos, runtime ou diffs.
- [x] Artifacts externos exigem audience e promoção/package.
- [x] RAG e objetos usam tenant/RLS/prefixo exclusivo; consulta cross-tenant falha.
- [x] Seed e mocks ficam fora dos perfis operacionais; AFlow permanece invisível.
- [ ] Chave exposta foi revogada e a substituta está somente no secret manager/env local.
- [ ] Cinco tenants reais foram provisionados em banco operacional limpo, com membership do operador e bases RAG separadas.
- [ ] Testes adversariais da matriz completa de papéis passaram na stack alvo.

## Missão real e entrega

- [ ] Missão criada pela UI pelo fluxo contratado, sem endpoint técnico direto.
- [ ] ContractFlow e ServiceDesk executaram `software_factory_ai_native_v2` com modelos por papel e custo real de até US$ 15 por missão.
- [ ] SSE, papéis/SOPs, handoffs, loops e topologia correspondem ao YAML persistido.
- [ ] Artifacts Markdown, `FileChange`, diffs e evidências foram persistidos.
- [ ] Sandbox executou backend tests/smoke, frontend tests/build, Playwright visual, axe e Bandit; qualquer falha real gerou correção e novo passe.
- [ ] Quality gates e HRS foram calculados sem influência de XP.
- [ ] Reviewer recebeu somente a projeção segura e registrou decisão idempotente.
- [ ] Homologation package foi promovido, aprovado e entregue.
- [ ] XP resultante referencia os ledger records corretos sem duplicação.
- [ ] Validation manifests comprovam todos os vínculos modelo→artifact/arquivo e fingerprints/propostas distintos.

## Operação

- [ ] Pause/step/resume e restart do worker foram comprovados.
- [ ] MCP negado e comando de sandbox não allowlisted foram bloqueados e auditados.
- [ ] Restore limpo, RPO/RTO, backup offsite e alerta real foram comprovados.
- [ ] VPS expõe somente portas autorizadas e passa o validador público OIDC/API/web.

A homologação só fecha quando todos os itens de missão real, segurança crítica e operação estiverem marcados com evidência anexada.
