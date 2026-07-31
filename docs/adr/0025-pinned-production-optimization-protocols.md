# ADR 0025 — Protocolos de otimização fixados em produção

## Status

Aceita como default operacional v2.13.2 por decisão do operador; rollout externo e alegações de ganho pendentes de benchmark e aprovação de readiness.

## Contexto

Ponytail oferece uma disciplina explícita de solução mínima e Cavekit um ciclo compacto de especificação, construção e backpropagação. Instalar hooks ou executar runtimes externos diretamente ampliaria a superfície de supply chain, permitiria atualização fora do controle da fábrica e contornaria as fronteiras existentes de tenant, orçamento, sandbox e ledger.

## Decisão

- Instalar no host de desenvolvimento o plugin Codex canônico `ponytail@ponytail`, com marketplace fixado no commit revisado, modo `full` persistente, auto-update desligado e confiança de hooks nunca contornada.
- Implementar adaptadores internos originais para o comportamento público revisado, fixados por versão e commit. Os hooks do host não são executados dentro das missões.
- Usar Ponytail em modo `full` em todos os papéis da v2.13.2. Minimalidade nunca remove requisitos, segurança, isolamento, acessibilidade, testes, observabilidade, HRS ou aprovação.
- Usar todas as etapas funcionais do Cavekit, curadas por papel. Uma etapa sem entrada válida termina `not_applicable`; nenhuma evidência é inventada.
- Registrar a ativação Cavekit como `registered` e concluir somente após step/unidade validada, relatório de sandbox ou quality gate persistido. `backprop` observa falha real e `deepen` ocorre apenas depois dos gates.
- Persistir cada ativação como `PluginInvocation` tenant-scoped, idempotente e ligada ao ledger/run/node/unidade.
- Produzir audit e debt como artifacts Markdown. `gain` usa somente tokens/custo reais da run e não atribui benchmarks upstream à plataforma.
- Exigir do Engineer referências exatas de requisito, invariante e teste. QA só promove o vínculo a `verified_contract` quando arquivo e relatório de sandbox aprovado existem.
- Expor manifests e métricas por APIs operacionais sem prompts, secrets ou conteúdo cross-tenant.

## Consequências

A política da fábrica é reproduzível e rollbackável sem executar código de terceiros nas runs. A migration `0015_production_plugin_runtime` adiciona o registro de invocações e os campos de rastreabilidade. v2.13.2 é o default para novas runs internas; só pode chegar aos clientes após benchmark, 17 gates, HRS, avaliação cega e decisão de readiness.

Não há alegação de economia ou qualidade superior até ContractFlow e ServiceDesk concluírem as comparações reais. Consulte [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
