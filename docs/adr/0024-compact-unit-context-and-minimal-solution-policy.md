# ADR 0024 — Contexto compacto por unidade e política de solução mínima

## Status

Aceita como candidata v2.13.1; rollout pendente de benchmark e aprovação humana.

## Contexto

O protocolo segmentado repetia o `ContextBundle` inteiro no plano, em cada seção/lote e na finalização. Instruções com a chave específica da unidade também alteravam o system prompt, reduzindo o reaproveitamento do cache do provider. Isso elevava custo sem aumentar a evidência disponível para a tarefa corrente.

## Decisão

- Preservar o bundle tenant-scoped completo como fonte congelada de auditoria e replay.
- Derivar uma visão determinística por unidade com goal, constraints, invariants, tarefa, falhas recentes, dependências diretas e referências limitadas por orçamento.
- Persistir hash, manifesto de referências e tokens source/sent/saved na própria `ExecutionUnit`.
- Manter a instrução global estável; chave, targets e dependências da unidade ficam depois do breakpoint, no user payload.
- Usar modelos rápidos apenas para manifestos e finalizações curtas configuradas. Conteúdo de arquitetura, código, review, QA, segurança e qualidade mantém o alias protegido.
- Aplicar uma hierarquia de reuso: código/artifacts existentes, biblioteca padrão, recursos nativos, dependências já instaladas e só então implementação adicional. A regra nunca autoriza omitir requisito, validação de fronteira, segurança, acessibilidade, tratamento de erro, teste ou evidência.
- Usar resultados de testes e decisões como evidência explícita de rework, sem criar um agente autônomo ou memória global com dados do cliente.

## Consequências

O custo teórico evitado pode ser calculado antes da chamada e comparado ao uso real do provider. A economia de cache continua sendo contabilizada somente quando o provider reporta leitura. A candidata não é promovida automaticamente: `ASF_AI_NATIVE_POLICY_VERSION` permanece em `2.13.0` até avaliação.

Os padrões foram adaptados conceitualmente de Ponytail e Cavekit após revisão somente leitura; nenhum hook, plugin, binário, subagente ou runtime externo foi instalado. Consulte [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
