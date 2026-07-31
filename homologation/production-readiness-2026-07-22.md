# Relatório de prontidão production-like — 2026-07-22

## Decisão

**NÃO LIBERAR PARA PRODUÇÃO PÚBLICA.**

A candidata está apta a continuar como piloto interno assistido. O fluxo
funcional, build, segurança de dependências, isolamento, backup/restore local e
carga de 50 usuários passaram. O stress obrigatório de 200 usuários falhou;
spike, soak, provider real, oito ofertas completas e aceite humano permanecem
sem evidência terminal.

## Ambiente e segurança

- Stack Docker Compose completa em dados isolados sob
  `/tmp/asf-production-e2e-20260722`.
- Volume original do usuário preservado e não montado nesta rodada.
- Provider configurado com placeholder inerte; nenhuma credencial anteriormente
  compartilhada foi reutilizada.
- PostgreSQL, Keycloak, MinIO, LiteLLM, Temporal, API, Web, Prometheus, Tempo,
  Collector, Grafana e sandbox Kind incluídos no escopo.

## Evidência executada

| Gate | Resultado | Evidência |
| --- | --- | --- |
| API em PostgreSQL fresco | PASSOU | `160 passed, 3 skipped`, 136,67 s; migrations `0001–0017` |
| TypeScript/build Web | PASSOU | Next.js 16.2.11, 33 rotas |
| Dependências Web | PASSOU | `npm audit --audit-level=high`: 0 vulnerabilidades |
| Playwright OIDC/UI | PASSOU COM SKIPS EXPLÍCITOS | `7 passed, 3 skipped`, 1,9 min |
| Compose base/full/VPS | PASSOU | `config --quiet` com placeholders não secretos |
| Observabilidade | PASSOU | span SDK → OTLP → Collector → Tempo recuperado por trace ID |
| Backup/restore local | PASSOU | dump + SHA-256, restore descartável, migration `0017`, hash-chain válida |
| Carga 50 usuários | PASSOU | 2.880 requests, 23,775 req/s, p95 3,843 s, 0 falha/timeout |
| Stress 200 usuários | **FALHOU** | 2.432 requests, 2.400 timeouts, taxa 98,684% |
| Spike 500 | BLOQUEADO | Não executado após falha do stress |
| Soak 20/8 h | BLOQUEADO | Não executado após falha do stress |
| Provider real e oito ofertas | BLOQUEADO | Credencial substituta/saldo e execução terminal ausentes |
| Owner e VP reais | BLOQUEADO | Aprovação humana real não foi simulada como aceite comercial |

Os três skips do Playwright são: homologação visível sem opt-in, engajamento
contratado ausente no banco limpo e cockpit sem ID de run concluída. Nenhum skip
foi convertido em sucesso.

## Defeitos encontrados e tratados

1. O harness de carga classificava timeout de transporte como sucesso. Agora
   aceita apenas 2xx, falha em erro inesperado, aquece endpoints e possui três
   testes unitários.
2. Projeções globais abriam sessões SQL aninhadas e podiam esgotar o pool. As
   rotas reutilizam a sessão tenant-scoped e restauram o contexto.
3. O catálogo fazia inicialização mutável em todo GET. A criação canônica ficou
   no startup; leituras são somente leitura.
4. Pacotes Office repetidos variavam por timestamp interno. O metadata OOXML é
   normalizado e 100 gerações consecutivas produziram o mesmo SHA-256.
5. O E2E passava uma identidade de VP diferente daquela provisionada no realm.
   O validador agora usa a identidade local canônica.
6. A tela Aprovações podia mostrar apenas carregamento sem contexto. Título e
   propósito aparecem imediatamente, antes da fila.
7. O Temporal parecia `running`, mas o banco não possuía `namespaces`; o worker
   encerrou. O schema isolado foi inicializado, o namespace `default` validado e
   o validador agora exige namespace e worker estável sem traceback.
8. Duas vulnerabilidades altas na árvore npm foram removidas com Next.js
   16.2.11, `sharp 0.35.3` e `js-yaml 4.3.0`.

## Evidências locais preservadas

- Backup: `/tmp/asf-production-e2e-20260722/evidence/backup/`
- Carga válida e stress:
  `/tmp/asf-production-e2e-20260722/evidence/load-single-optimized/`
- Critérios e estado consolidado: `docs/operational-readiness.md`

## Bloqueadores para promoção

1. Projetar backpressure/escalabilidade e repetir stress 200 até timeout ≤ 3%.
2. Somente depois, executar spike 500 e soak 20 por oito horas.
3. Rotacionar a credencial exposta e executar ContractFlow, ServiceDesk e as
   oito ofertas com provider real, sandbox, 17 gates, HRS, Ponytail e Cavekit
   terminais.
4. Executar onda multi-tenant `2/2/1 + sexto enfileirado`, fault injection e
   recovery/RTO medido.
5. Realizar as sessões de usabilidade e aprovação com owner e VP reais.
6. Executar canário, observar SLO público e validar com usuários externos antes
   de `market_ready`.

Até esses gates passarem, o estado correto permanece `candidate`.
