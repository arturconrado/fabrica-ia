# Primeiro cliente — piloto assistido 2.1

Este é o corte operacional mínimo para receber um cliente sem declarar produção
pública. O alvo verificável é `internal_assisted_pilot_ready`; `market_ready`
continua exigindo staging/VPS, DNS/TLS, storage externo, alertas, canário de 72
horas, SLO e validação de um design partner.

## Limite operacional

- Um tenant exclusivo para o cliente.
- Owner opera configuração, contrato, execução, recovery e incidentes.
- VP atua como `engagement_manager` e decide plano, qualidade, entregáveis e
  entrega final por uma identidade distinta.
- Nenhuma aprovação ou evidência sintética conta para liberação comercial.
- Ações externas exigem evidência. Agentes não elevam WIP, alteram contrato,
  aprovam o próprio trabalho ou executam shell fora da allowlist.
- O portfólio 2.1 e o workflow 2.14.0 permanecem candidatos até o gate e a
  decisão humana. 2.0 e 2.13.2 continuam disponíveis para replay.

## O que o corte 2.1 implementa

- Migration `0018`: `operator_profile` tenant-scoped e `operation_key` para
  grupos técnicos.
- Pilot `software_product` e Engineering `engineering_validation`: cada grupo
  usa exatamente um `WorkflowRun`, uma `ServiceExecution` e um slot; seus
  entregáveis recebem revisões distintas derivadas da mesma evidência.
- Autoria delimitada por disciplina, `base_sha256`, diff textual, model call,
  step, evento e `FileChange` para cada alteração.
- QA produz testes; DevOps produz Docker/Compose; revisores devolvem correções ao
  papel proprietário com tentativas limitadas.
- Download integral do engajamento somente depois de entregáveis reais, checks
  completos e decisão final do VP.
- Perfis profissionais adaptam a jornada sem ampliar autoridade.
- Avaliação determinística 2.14.0 versus 2.13.2 em dataset fixo e três
  repetições reais, sempre com promoção humana.

## Gates ainda obrigatórios

Implementação verde não equivale a homologação. A mesma execução candidata
precisa produzir e persistir:

1. PostgreSQL/RLS migrado de `0001` a `0018` e todas as regressões verdes.
2. As oito ofertas 2.1 com provider real, incluindo dois ciclos separados do AI
   Office iniciados por comando humano.
3. AtlasLog Discovery sem run técnico, NuvemSul Engineering e NovaMec Pilot com
   exatamente um run técnico cada, código/testes/Compose baixáveis, 17 gates,
   HRS ≥ 90 e Ponytail/Cavekit terminais.
4. Três repetições reais de 2.13.2 e 2.14.0 para os dois casos técnicos, sem
   regressão e com custo/tokens medianos no máximo 20% acima do baseline.
5. Onda multi-tenant `2/2/1`, sexto item enfileirado, fairness, isolamento e
   ausência de slot órfão.
6. Fault injection, restart, cancelamento tardio, sandbox negado,
   backup/restore, RPO zero e RTO p95 ≤ 5 minutos.
7. Playwright owner/VP sem skip ou flake, acessibilidade e quatro viewports.
8. Carga `2/20/50/200`, spike `500` e soak `20/8h` da mesma rodada.
9. Decisões reais e distintas de owner e VP e avaliação persistida sem blocker.

Antes de chamadas pagas, a chave rotacionada entra somente por secret/env. O
simulador deve comprovar expectativa ≤ US$ 15, cenário conservador ≤ US$ 30 e
hard stop global em US$ 50.

## Sequência de fechamento

```bash
make production-e2e-preflight
make production-e2e-local
make production-e2e-human
make production-e2e-load
make production-e2e-pilot-final
```

As fases usam o mesmo `ASF_PRODUCTION_E2E_RUN_ID`, são resumíveis e só gravam o
marcador após sucesso. `pilot-final` exige as jornadas realistas, a comparação
2.13.2/2.14.0 e o case comercial; ele não promove automaticamente o catálogo.

## Decisão go/no-go

O cliente só entra quando `production-e2e-pilot-final` retorna zero e a
avaliação autenticada `internal_assisted_pilot_ready` não contém blocker. Até
lá, demonstrações são internas e dados reais de cliente não devem ser
processados.
