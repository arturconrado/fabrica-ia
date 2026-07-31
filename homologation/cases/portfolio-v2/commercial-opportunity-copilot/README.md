# Case real — Opportunity-to-Proposal Copilot

Este é o caso canônico da candidata Portfólio 2.1. O produto será usado pelo owner e pelo VP para qualificar oportunidades, recomendar ofertas e preparar propostas editáveis com aprovação four-eyes. Os registros de runs 2.0 nesta pasta são históricos e permanecem inalterados.

O bundle não contém dados pessoais ou dados de prospects. Os 24 cenários
controlados cobrem as oito ofertas três vezes; oito deles incluem prompt
injection, tentativa de elevação de autoridade, fabricação de evidência ou
acesso cross-tenant. Depois da avaliação técnica, owner e VP devem realizar uma
rodada adicional com uma oportunidade interna real.

`evaluation-inputs.jsonl` é a única versão entregue ao produto durante a
avaliação. Os rótulos de `evaluation-dataset.jsonl` permanecem fora da base de
conhecimento e são lidos apenas pelo avaliador determinístico. Isso evita que o
agente “aprenda” as respostas do próprio benchmark.

Os fluxos de produção agentic usam também
[`../realistic-agentic-journeys.json`](../realistic-agentic-journeys.json): oito
contextos sintéticos distintos, um por oferta, com fatos, sinais específicos,
alegações proibidas e uma fonte adversarial. O objetivo é testar o processo
contratado e a qualidade dos entregáveis, não apenas a classificação comercial.

## Estado da execução real

A primeira tentativa de planejamento de 2026-07-21 alcançou o OpenRouter pela
stack real, mas foi bloqueada por créditos insuficientes. A repetição com uma
credencial autorizada concluiu com sucesso e persistiu um plano contextualizado,
versionado e rastreável. Essa instância foi posteriormente ativada por uma
aprovação marcada como `SIMULAÇÃO DE HOMOLOGAÇÃO`; ela continua útil como
evidência técnica, mas não representa decisão comercial do VP.

Uma nova instância isolada, `vp-demo-20260723`, foi materializada em `draft`
para a apresentação e decisão pessoais do VP. Seu plano ainda depende de uma
credencial rotacionada e não exposta. Consulte a
[evidência da falha controlada](runs/2026-07-21-openrouter-plan-attempt.md), a
[evidência do plano real](runs/2026-07-21-openrouter-plan-success.md) e o
[ensaio da apresentação ao VP](runs/2026-07-23-vp-demo-rehearsal.md).

## Pré-condições

- stack full ativa com PostgreSQL, OIDC, Temporal, provider real, MinIO e sandbox;
- tenant de homologação já provisionado;
- owner e VP como identidades distintas, com papéis `owner` e `engagement_manager`;
- credencial do provider válida e budget autorizado.

Os tokens são fornecidos apenas ao processo e nunca são gravados:

```bash
export ASF_HOMOLOGATION_API_BASE_URL=http://localhost:8000
export ASF_HOMOLOGATION_TENANT_ID=<tenant-id>
export ASF_HOMOLOGATION_OWNER_TOKEN=<owner-token>
export ASF_HOMOLOGATION_VP_TOKEN=<vp-token>
```

## Execução auditável

```bash
python scripts/run-portfolio-homologation-case.py validate
python scripts/run-portfolio-homologation-case.py bootstrap
python scripts/run-portfolio-homologation-case.py plan
python scripts/run-portfolio-homologation-case.py approve
python scripts/run-portfolio-homologation-case.py activate
python scripts/run-portfolio-homologation-case.py queue --confirm QUEUE_REAL_PROVIDER_WORK
python scripts/run-portfolio-homologation-case.py status
```

`bootstrap`, `plan`, `activate` e `queue` usam a identidade do owner. `approve` exige estritamente a identidade `engagement_manager`. As ações consultam o estado persistido e podem ser retomadas, mas não contornam versão, idempotência, ledger ou four-eyes.

## Avaliação realista dos entregáveis

Valide primeiro o contrato dos oito cenários:

```bash
cd apps/api
uv run python ../../scripts/evaluate-agentic-journeys.py validate
```

Uma rodada candidata deve exportar `agentic-journey-evidence/1.0` com uma
jornada completa e pelo menos duas repetições do entregável-probe de cada
cenário. A jornada completa cobre todos os `template_key`; as repetições medem
estabilidade sem multiplicar desnecessariamente o custo do provider. Todas
registram identidades distintas de produtor e revisor, model calls e ledger; a
jornada completa comprova modos de processo e evidência técnica quando
aplicável. A avaliação é determinística e não chama outro modelo:

```bash
cd apps/api
uv run python ../../scripts/evaluate-agentic-journeys.py evaluate \
  --evidence ../../artifacts/portfolio-v2/agentic-journey-evidence.json \
  --output ../../artifacts/portfolio-v2/agentic-journey-evaluation.json
```

Cada revisão v2 precisa conter as cinco seções do template, substância mínima,
claims de evidência, referências tenant-scoped, riscos, próximos passos e
conteúdo distinto dos demais entregáveis. Falha nesse contrato bloqueia a
submissão ao VP com `DELIVERABLE_CONTRACT_NOT_MET`; aprovação continua
exclusivamente humana.

O case comercial possui um segundo gate específico. Ele exige a trilha completa
da produção agentic, 17 gates, HRS, Ponytail/Cavekit, três rodadas provider-real
dos 24 inputs sem rótulo, acurácia mínima de 90%, custo, latência, erro de
provider, grounding e zero violação de autonomia:

```bash
cd apps/api
uv run python ../../scripts/evaluate-commercial-ai-case.py validate
uv run python ../../scripts/evaluate-commercial-ai-case.py evaluate \
  --evidence ../../artifacts/portfolio-v2/commercial-ai-case-evidence.json \
  --output ../../artifacts/portfolio-v2/commercial-ai-case-evaluation.json
```

O arquivo `commercial-ai-case-evidence/1.0` separa `production_evidence` das
três `evaluation_runs`. A produção registra agentes, entradas, model calls,
artifacts, revisão e eventos. Cada rodada registra uma predição por input, fatos,
hipóteses, perguntas, riscos, dependências, proveniência, estado
`pending_vp`, custo, p95 e decisão identificada do VP. O avaliador deriva os
resultados; nenhum campo `passed` enviado pelo executor é aceito.

## Dois modos comerciais mínimos

A fábrica também valida
[`../commercial-operation-matrix.json`](../commercial-operation-matrix.json):

1. AtlasLog contrata somente `AI Value Discovery` e recebe diagnóstico,
   oportunidades, arquitetura, roadmap e apresentação; não há `technical_run`
   nem código artificial para preencher o escopo.
2. MetalQuote contrata `AI Use Case Pilot` para um sistema de orçamentação
   agêntica. Nesse caso, o gate exige código-fonte editável, `FileChange` com
   diff, testes, relatórios, 17 gates, HRS, Ponytail/Cavekit e pacote com hash.

Os dois cases são standalone, vivem em tenants distintos e também cabem na
mesma onda de execução. O serviço consultivo e o MVP técnico preservam equipes,
entregáveis, evidências e critérios próprios.

Para uma nova apresentação ou rodada de homologação, preserve o histórico da
instância anterior e use o mesmo sufixo seguro em todas as transições:

```bash
python scripts/run-portfolio-homologation-case.py validate --instance-id vp-demo-20260723
python scripts/run-portfolio-homologation-case.py bootstrap --instance-id vp-demo-20260723 --reuse-canonical-knowledge
python scripts/run-portfolio-homologation-case.py plan --instance-id vp-demo-20260723 --reuse-canonical-knowledge
```

O sufixo cria contrato, engajamento, base de conhecimento e chaves de
idempotência isolados. A geração do plano continua exigindo provider autorizado;
a aprovação continua pertencendo exclusivamente à identidade real do VP.
Quando o limite de bases do tenant já tiver sido atingido,
`--reuse-canonical-knowledge` reutiliza explicitamente a base do case no mesmo
tenant; documentos da instância recebem `source_ref` próprio e nenhum dado é
reutilizado entre tenants.

## Fluxo visual do VP

1. Entre com a identidade pessoal do VP; não reutilize a sessão do owner.
2. O **Painel do VP** mostra somente planos e revisões que aguardam decisão.
3. Abra `Piloto real — Opportunity-to-Proposal Copilot` e confira escopo, workstreams propostos, entregáveis e riscos.
4. Escreva um comentário de decisão. O botão **Aprovar e liberar para o owner** permanece desabilitado sem justificativa.
5. Depois da decisão, encerre a sessão. O owner verá **Ativar e materializar a operação** e seguirá com a execução.

O perfil do VP não exibe work queue, runtime, secrets, identidades ou o botão de ativação. O E2E automatizado percorre esse fluxo somente até a habilitação do botão; a decisão real permanece humana.

Após a ativação, a mesma fila conduz o VP por três decisões adicionais:

1. **Qualidade:** verificar gates, HRS, rastreabilidade e artifacts autorizados.
2. **Entregável:** revisar conteúdo, critérios, DoD, evidências, riscos e próximos passos; aprovar, solicitar ajustes ou rejeitar com comentário.
3. **Entrega final:** baixar o pacote editável e registrar destinatário, canal e referência do aceite.

O owner produz e submete; o VP valida e entrega. O endpoint genérico de aprovações não pode alterar entregáveis de serviço, evitando decisões duplicadas ou estados divergentes.

## Encerramento

Agent/technical work é enfileirado pelo runner. Entrevista, demonstração, revisão, entrega, evidências dos checks e decisão final permanecem tarefas explícitas na UI. O caso não pode ser marcado como aprovado apenas pelo resultado do script.
