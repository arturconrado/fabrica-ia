# ADR-0021: Workflow AI-native v2, proveniência e sandbox

## Status

Accepted

## Context

O executor v1 chamava o modelo, mas descartava sua saída e materializava um produto ContractFlow fixo. Isso não comprova que a fábrica consegue produzir soluções distintas nem liga cada artifact e diff à chamada que o originou.

## Decision

Novas runs técnicas usam `software_factory_ai_native_v2`. Um executor genérico carrega o YAML persistido, o prompt e a skill versionados de cada papel. O modelo retorna `AgentStepResult`; schema, audiência, referências, paths, tamanho, decisão e hash-base são validados antes de qualquer escrita.

Cada passo persiste `AgentStepExecution`, hashes de entrada/saída, `ModelCall`, artifacts e `FileChange`. O contexto é limitado, tenant-scoped e inclui somente RAGs explicitamente autorizados. A IA nunca escolhe comandos: ela pode solicitar apenas perfis nomeados, e a plataforma executa comandos exatos em Jobs Kubernetes non-root, sem rede e com limites.

O roteamento usa `asf-fast`, `asf-reasoning` e `asf-code`. O gateway contabiliza uso real e bloqueia novas chamadas no teto da run ou do tenant. Testes, segurança, 17 gates, HRS, pricing, entitlement e decisões humanas permanecem determinísticos.

## Consequences

- Runs v1 permanecem consultáveis, mas não recebem novas funcionalidades.
- Falha de schema, referência, orçamento, sandbox ou gate bloqueia a run.
- Rework automático e humano cria nova iteração e preserva o histórico.
- Homologação exige dois produtos distintos, evidência model→output, aplicação inicializável e custo de até US$ 15 por missão.
