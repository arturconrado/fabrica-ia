# Evidência de homologação — planejamento via OpenRouter

## Resultado

- Data: 2026-07-21
- Case: `internal-commercial-opportunity-copilot-v1`
- Oferta contratada: `ai_use_case_pilot_sprint` versão `2.0`
- Tenant: `local-dev`
- Estado final do engajamento: `draft`
- Estado final do plano: não criado
- Classificação: `external_constraint`
- Decisão de liberação: bloqueada

## Recursos materializados

- Contract: `019f85cb-2ec4-73ca-8dd2-5da8d9b2751b`
- Entitlement: `019f85cb-2f56-7c9f-b779-06a795c1e3ea`
- Program: `019f85cb-2ea5-7064-a3b7-2bb285928747`
- Knowledge base: `605c5c70-26be-4521-89c2-fd773381d958`
- Engagement: `019f85cb-30fb-7a14-9df0-e653e6f92d6b`

## Chamada real ao provider

- Rota: API da fábrica → LiteLLM → OpenRouter
- Alias de modelo: `asf-reasoning`
- Model call persistido: `cc42ac0c-a70a-4cfa-8dfc-a6ed3d868d8a`
- Resultado: HTTP `402`, créditos insuficientes na conta OpenRouter
- Duração: `9.945 s`
- Custo registrado: `US$ 0.00`
- Ledger: evento `ai.invocation_recorded`, sequência tenant `1941`
- Segredos: nenhum valor foi gravado neste relatório

## Controles verificados

- O provider reconheceu a credencial configurada e rejeitou a operação por saldo.
- Nenhum plano parcial foi persistido.
- O contrato, entitlement, programa, base e engajamento permaneceram íntegros.
- A falha do provider e sua invocação foram persistidas no ledger append-only.
- Não restaram locks PostgreSQL após o encerramento da requisição.
- Nenhum retry de workflow, ativação, fila paga ou aprovação humana foi disparado.
- O gate four-eyes do VP não foi contornado.

## Achado e correção

A primeira tentativa revelou que a consulta de conhecimento mantinha o lock do
ledger enquanto o `ModelGateway` tentava persistir evidência em uma sessão
independente. A consulta tenant-scoped passou a concluir sua própria transação
antes da chamada ao provider. A repetição retornou o `402` em tempo limitado,
persistiu a evidência e liberou todos os locks. Erros `402`, `Payment Required`
e `Insufficient credits` também passaram a ser classificados como
`budget_or_isolation`, portanto não-retryáveis.

## Mitigação e próximo gate

Adicionar saldo à conta associada à chave OpenRouter já configurada e repetir:

```bash
python3 scripts/run-portfolio-homologation-case.py plan --timeout 300
```

Se o plano for gerado e validado contra o schema, ele deverá permanecer
`awaiting_approval` até revisão real do VP. Aprovação, ativação e execução dos
work items não podem ser realizadas por uma identidade técnica em nome do VP.
