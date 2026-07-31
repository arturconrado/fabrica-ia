# Evidência de homologação — plano real gerado via OpenRouter

## Resultado

- Data: 2026-07-21
- Case: `internal-commercial-opportunity-copilot-v1`
- Oferta contratada: `ai_use_case_pilot_sprint` versão `2.0`
- Tenant: `local-dev`
- Estado do engajamento: `awaiting_approval`
- Estado do plano: `draft`, versão `1`
- Decisão de liberação: pendente da revisão four-eyes do VP

## Recursos e rastreabilidade

- Contract: `019f85cb-2ec4-73ca-8dd2-5da8d9b2751b`
- Entitlement: `019f85cb-2f56-7c9f-b779-06a795c1e3ea`
- Program: `019f85cb-2ea5-7064-a3b7-2bb285928747`
- Knowledge base: `605c5c70-26be-4521-89c2-fd773381d958`
- Engagement: `019f85cb-30fb-7a14-9df0-e653e6f92d6b`
- Engagement plan: `019f864a-7200-7d80-a69a-f8720644c52e`
- Model call: `b826a985-f757-45ac-9a6b-6be883ef8997`

## Chamada real ao provider

- Rota: API da fábrica → LiteLLM → OpenRouter
- Alias e papel: `asf-reasoning` / `reasoning`
- Resultado: `success`, com `finish_reason=stop`
- Duração: `126.622 s`
- Tokens de entrada: `6.079`
- Tokens de saída: `7.367`
- Custo persistido: `US$ 0.128742`
- Retry: `initial`; nenhum retry adicional foi necessário
- Ledger: `knowledge.retrieval_completed` na sequência `1943`
- Ledger: `ai.invocation_recorded` na sequência `1944`
- Ledger: `engagement.plan_generated` na sequência `1945`
- Segredos: nenhum valor de credencial foi gravado nesta evidência

## Conteúdo materializado

O plano foi validado contra o schema e materializou:

- 6 workstreams: problema, desenho, dados, construção, avaliação e evolução;
- 13 entregáveis canônicos do `AI Use Case Pilot 2.0`;
- modos de execução `agent`, `technical_run`, `integration` e `human`;
- dataset controlado com 16 cenários e meta de acurácia mínima de 90%;
- aprovação four-eyes obrigatória, sem precificação, envio externo ou aprovação autônoma;
- 17 gates técnicos, HRS mínimo 90 e estados terminais de Ponytail/Cavekit;
- fontes abertas e formatos editáveis, evidências, manifesto e pacote final;
- riscos, limitações, dependências e próximos passos específicos para o case.

## Controles verificados

- O conteúdo foi contextualizado com três referências tenant-scoped da knowledge base.
- A saída separa objetivos, etapas, entregáveis, riscos e próximos passos.
- O plano não criou preços, entrevistas, integrações ou benefícios inexistentes.
- O hash de entrada e o hash de saída foram persistidos no `ModelCall`.
- O ledger append-only avançou de forma sequencial até `1945`.
- Nenhum workstream, item, entregável ou acceptance check foi materializado antes da aprovação.
- Nenhuma ativação, execução técnica, pacote ou entrega foi disparada antecipadamente.
- O ator que gerou o plano continua impedido de aprová-lo.

## Próximo gate humano

O VP deve revisar o plano pela identidade `engagement_manager` e registrar um
comentário explícito. Somente depois dessa decisão o owner poderá ativar o
engajamento e enfileirar trabalho pago. A automação não representa nem substitui
essa decisão humana.
