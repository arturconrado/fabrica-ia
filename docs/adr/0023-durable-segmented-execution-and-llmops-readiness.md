# ADR-0023 — Execução segmentada durável e readiness LLMOps

- Status: aceito
- Data: 2026-07-20

## Contexto

O executor AI-native já possuía grafo YAML, contexto tenant-scoped, structured output, sandbox, gates e aprovação humana, mas uma execução longa ainda podia concentrar planejamento, geração e persistência dentro de uma única fronteira operacional. Isso aumentava o custo de recuperação, a chance de repetir chamadas e a dificuldade de provar cache, RPO/RTO e proveniência por unidade.

## Decisão

Novas runs usam `executor_protocol_version=segmented-output-v1`. O protocolo preserva os workflows v2.11, v2.12 e v2.13 e separa:

1. plano curto do node;
2. unidades ordenadas e idempotentes;
3. uma model call por unidade;
4. fragmentos imutáveis ou lotes de até quatro arquivos;
5. montagem determinística;
6. sandbox, quality e transição do grafo;
7. espera humana e entrega.

Temporal registra `SoftwareFactoryAINativeWorkflowV2`, mantendo o workflow anterior para históricos. `plan_segmented_node` apenas congela contexto e manifesto. Cada `execute_output_unit` executa uma única unidade e confirma seu hash. `assemble_artifact` reconcilia fragments/files, finaliza o step e permite que o mesmo `WorkflowTransitionEngine` puro usado inline aplique a transição.

Cada unidade usa a identidade `tenant/run/node/iteration/unit/action`, no máximo três tentativas e duas continuações. Outputs confirmados são exatamente uma vez no banco/ledger; chamadas externas continuam at-least-once. Replay com payload ou hash divergente bloqueia. Patches exigem `base_sha256`.

O cache é provider-aware e limitado ao prefixo global estável: system prompt, skill, schema e toolset. Demandas, RAG, artifacts, lessons privadas e arquivos ficam fora da chave e do breakpoint. Economia só existe quando o provider reporta leitura e valor economizado.

Learning global passa a ter registro tenant-free de padrões sanitizados e deployments tenant-scoped. Promoção exige três runs, dois tenants, benchmark aprovado e decisão administrativa. Rollback muda somente o ponteiro do tenant.

## Consequências

- Crash após uma unidade confirmada retoma pela unidade seguinte sem duplicar artifact, diff ou evento.
- Pause/resume do operador e pausa por orçamento são signals/checkpoints; orçamento e isolamento não geram retry automático.
- O cockpit pode mostrar unidade, tentativa, heartbeat, model call, fragmento, hash, cache e trace sem expor prompt ou chain-of-thought.
- A observabilidade não usa `tenant_id` como label Prometheus; detalhes permanecem nas APIs tenant-scoped. O papel operacional continua sujeito a RLS e acessa somente agregados técnicos por uma função `SECURITY DEFINER` sem identificadores, criada em `0013`.
- Em produção, `ASF_OTEL_EXPORTER_OTLP_ENDPOINT` é obrigatório. API e worker exportam em batch para o collector interno e Tempo; não existe fallback silencioso para spans descartados.
- A complexidade de persistência aumenta e requer migrations aditivas `0010`, `0011`, `0012` e `0013`.
- A implementação não demonstra `pilot_ready` ou `market_ready` por si só. Esses estados exigem missões reais, recovery, cache aquecido e SLOs persistidos.

## Alternativas rejeitadas

- Migrar para outro framework de agentes ou microserviços: aumentaria superfície sem resolver a evidência operacional deste corte.
- Cache de resposta ou artifact de cliente: risco de isolamento e replay incorreto.
- Paralelismo dentro da run: dificulta WIP, budget e ordem determinística; o piloto mantém sequência por run e paralelismo somente entre runs.
- Promoção automática de prompts/lessons: conflita com governança humana e reprodutibilidade.
