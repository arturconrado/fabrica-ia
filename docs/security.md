# Segurança e matriz de acesso

## Autenticação

- A web usa OIDC Authorization Code + PKCE; o BFF mantém tokens em cookies `HttpOnly`, `SameSite=Lax` e `Secure` fora do localhost.
- Refresh, expiração, logout e retry de um único 401 são centralizados. O link de logout usa navegação sem prefetch para que uma leitura da UI nunca encerre a sessão.
- Bearer, senha e refresh token não entram no DOM, `localStorage`, `sessionStorage` ou `NEXT_PUBLIC_*`.
- A API valida issuer, audience, assinatura JWKS, membership ativa, papel e tenant em cada request.

## Matriz de papéis

| Área | Operação | Reviewer/sponsor | Auditor | Admin |
|---|---|---|---|---|
| Portfólio, missões, agents e runtime | leitura/escrita conforme entitlement | negado | negado | permitido |
| Knowledge/RAG | leitura/escrita no tenant | negado | negado | permitido |
| Inbox e item de revisão | permitido | somente projeção segura | somente leitura | permitido |
| Aprovar/rejeitar/pedir mudanças | permitido quando autorizado | permitido; comentário obrigatório para rejeição/mudança | negado | permitido |
| Logs, prompts, custos internos e diffs | permitido | negado | negado | permitido |
| Tenants, membros, contratos e entitlements | conforme papel | negado | negado | owner/super_admin/tenant_admin/admin |

Papéis operacionais: `owner`, `super_admin`, `tenant_admin`, `engagement_manager`, `consultant`, `admin` e `operator`. Papéis de decisão: `client_sponsor`, `process_owner` e `reviewer`; `auditor` é somente leitura. A API, não o menu, é a autoridade final.

## Isolamento e saída de dados

- Toda consulta de negócio exige contexto tenant e PostgreSQL com `FORCE ROW LEVEL SECURITY`; o portfólio troca explicitamente a sessão RLS para cada membership antes de calcular o resumo.
- Projetos, runs, ledger, artifacts, arquivos, testes, custos, knowledge e batches são tenant-scoped. Objetos usam prefixo `tenants/{tenant}/...`.
- Artifacts possuem `audience=internal|reviewer|client`. A API de revisão só entrega artifacts promovidos ou presentes no package e remove paths, prompts, logs, custos e diffs internos.
- Markdown é renderizado sem HTML bruto. Paths de workspace são validados contra traversal.
- O RAG guarda conteúdo e índice separados por tenant. Perguntas e conteúdo bruto não entram no ledger; geração por LLM exige opt-in e envia apenas trechos autorizados daquele tenant.

## Runtime e auditoria

- Toda mutação relevante registra evento no ledger append-only; arquivos gerados por run produzem `FileChange` com diff.
- Comandos de sandbox são allowlisted e executados no namespace Kubernetes isolado. MCP exige `ToolPolicy` tenant-scoped.
- Model calls, sandbox executions, decisões, gamificação e invocações MCP são persistidos com proveniência.
- XP é projeção idempotente do ledger e nunca concede permissão, altera HRS ou contorna aprovação.
- Perfis operacionais exigem LiteLLM; fixtures e provider mock são aceitos somente quando `ASF_RUNTIME_PROFILE=test`.

## Gates antes de exposição pública

- Rotacionar toda credencial exposta e usar secret manager.
- Executar testes adversariais de cinco tenants, matriz completa de papéis e RLS PostgreSQL.
- Comprovar restore limpo, RPO/RTO, backup offsite e recebimento de alertas.
- Validar PVC, NetworkPolicy e RuntimeClass do sandbox no cluster alvo.
- Manter a operação assistida até esses gates e uma missão real completa estarem documentados.
