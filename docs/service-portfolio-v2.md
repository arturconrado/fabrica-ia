# Portfólio de serviços de IA 2.x

## Candidata 2.1 — primeiro cliente assistido

O snapshot 2.0 abaixo permanece imutável para reprodução histórica. A candidata
2.1 é derivada em memória desse snapshot, fixa o workflow técnico 2.14.0 e não
migra engajamentos existentes.

As diferenças contratuais e operacionais de 2.1 são deliberadamente pequenas:

- Pilot agrupa arquitetura, piloto, dataset e relatórios de teste, segurança e
  qualidade na operação `software_product`;
- Engineering agrupa templates técnicos e quality gates na operação
  `engineering_validation`;
- cada grupo materializa um único work item interno `technical_run`, uma
  `ServiceExecution`, um `WorkflowRun` e um slot, e depois distribui evidências
  em revisões específicas de cada entregável;
- ofertas sem construção de software não criam código ou run técnico artificial;
- retry/cancel afeta o grupo inteiro; ajuste de código cria novo run e preserva
  o anterior no ledger;
- pacotes integrais incluem fontes reconstruídas por `FileChange`, testes,
  Compose, 17 gates, HRS, Ponytail/Cavekit, traceabilidade e hashes.

`GET /api/v1/engagements/{id}/package/download` falha fechado até que todos os
entregáveis e checks reais estejam terminais e um VP ativo tenha registrado a
decisão final. `PATCH /api/v1/auth/me/operator-profile` seleciona apenas a
apresentação profissional; não altera RBAC nem a ação segura.

Readiness, evidências e decisões aceitam a versão alvo 2.1. O gate compara
2.14.0 com 2.13.2 em dataset fixo, três repetições reais por caso técnico e
promoção humana. `internal_assisted_pilot_ready` é o máximo deste corte;
`market_ready` segue bloqueado por staging, canário, SLO e design partner.

## Snapshot histórico 2.0

O catálogo canônico está em `apps/api/app/service_delivery/portfolio_v2.yaml`. A versão 1.0 continua imutável; a 2.0 nasce como `candidate` e pode ser contratada somente para homologação interna até a promoção humana.

## Jornada e ofertas

A jornada é: identificar oportunidades → priorizar investimentos → estabelecer governança → implantar capacidades → validar casos de uso → acelerar adoção → operar continuamente.

As oito ofertas preservam seus códigos técnicos. Apenas a apresentação de `ai_use_case_pilot_sprint` muda, na versão 2.0, para **AI Use Case Pilot**. Nome, descrição, processos, atividades, equipe, entregáveis estruturados, formatos, critérios específicos e os dez checks corporativos pertencem ao snapshot de `OfferingVersion`.

### Jornada modular na interface

`/service-catalog` apresenta somente as oito ofertas da versão operacional 2.0
na área principal. Versões históricas continuam acessíveis em uma seção
recolhida. Cada oferta possui uma página em
`/service-catalog/{offering_version_id}` com:

- todas as etapas, atividades e modos de execução;
- equipe curada, duração e responsáveis pela aprovação;
- todos os entregáveis, formatos, seções, evidências e critérios de aceite;
- Definition of Done específico e os dez checks corporativos;
- compromisso da oferta, fatores externos e o comando para iniciar o serviço.

A jornada é modular. Uma oferta pode ser contratada e operada isoladamente,
várias ofertas podem avançar em paralelo, ou o cliente pode percorrer a
sequência completa. Cada engajamento mantém equipe de agentes, budget, estado,
artifacts, checks e aprovações próprios. A fábrica só encadeia duas trilhas
quando existe `EngagementDependency` explícita e tenant-scoped; autonomia dos
agentes não autoriza criar dependências, aprovar artifacts ou alterar contrato.

`/engagements` organiza os serviços simultâneos em um quadro
`Plano → Aprovação → Execução → Entrega`. O cartão de cada engajamento abre sua
esteira, onde o roteiro completo da oferta contratada permanece disponível por
divulgação progressiva.

## Operação de ponta a ponta

1. Um contrato ativo e seus entitlements autorizam a criação do engajamento.
2. O plano contextualizado preserva todos os templates contratados e registra quem o produziu.
3. Outra identidade aprova o plano; a ativação materializa workstreams, entregáveis, itens, checks e equipe.
4. Na versão 2.0 com aprovação real, a própria ativação cria `ServiceExecution`: itens `agent` e `technical_run` entram na fila durável; itens `human` e `integration` ficam imediatamente disponíveis para registro de evidência sem ocupar WIP de computação. Aprovação sintética nunca inicia execução nem custo. O endpoint `POST /api/v1/service-work-items/{id}/execute` permanece para fluxos históricos e operação manual excepcional.
5. O dispatcher usa prioridade, prazo e round-robin, com cinco itens globais e dois por tenant. O excedente continua `queued`.
6. Temporal persiste tentativa, heartbeat, custo e evidência. `technical_run` delega ao workflow AI-native completo. Ao registrar evidência de uma atividade `human` ou `integration`, a execução volta automaticamente à fila para um agente sintetizar o artifact rastreável.
   Cancelamento de execução ativa passa por `cancel_pending`; o slot continua ocupado até Temporal e eventual workflow AI-native delegado estarem terminais. Falha de confirmação esgota tentativas limitadas e termina bloqueada com evidência, nunca em retry infinito.
7. Cada template seleciona o agente responsável da equipe curada, sua base de conhecimento e o menor limite entre o budget do papel e o budget da operação. Toda revisão gera artifact Markdown exibível e é submetida automaticamente à fila do VP. Aprovação e entrega exigem decisão humana; o produtor não pode aprovar a própria revisão.
8. Cada check do DoD exige referências persistidas e decisão de uma identidade diferente. Restrição externa exige impacto e mitigação.
9. O pacote editável contém fontes, Office/CSV/JSON quando aplicável, manifesto, MIME type, tamanho e SHA-256.

O AI Office só abre um novo ciclo por comando humano depois que o anterior estiver entregue e aceito. Esse comando autoriza e enfileira o trabalho de máquina do ciclo; nenhum ciclo seguinte nasce sozinho. A homologação da oferta exige dois ciclos completos.

## Papéis de dois operadores

- `owner`: contratos, configuração, execução, recovery e incidentes.
- `engagement_manager`: prioridade, revisão, checks, restrições externas e entrega final.

O controle four-eyes é aplicado no plano, na revisão do entregável e nos checks. O VP não recebe secrets, administração global de identidades nem shell. Atividades com clientes são registros externos com participantes, materiais, data e aceite.

### Esteira simples na interface

1. O owner abre o engajamento, contextualiza o case e gera o plano com o provider configurado.
2. O VP acessa o **Painel do VP** ou **Aprovações**, abre o plano pendente e registra um comentário de decisão. Sem comentário suficiente, a interface não habilita a aprovação.
3. Após a aprovação, somente o owner vê **Ativar e materializar a operação**. A ativação cria equipe, workstreams, itens, entregáveis e checks a partir do snapshot contratado.
4. O owner acompanha fila, execução, retry/cancel e registra evidências das atividades humanas ou externas. Agentes e execuções técnicas já são enfileirados pela ativação; o VP não vê esses controles operacionais.
5. A fábrica produz cada entregável e o submete automaticamente à fila de decisão. O VP abre o workspace do entregável, lê o conteúdo e valida critérios de aceite, Definition of Done, evidências, riscos, próximos passos e proveniência antes de aprovar, pedir ajustes ou rejeitar.
6. Depois da aprovação, o VP baixa o pacote editável e confirma destinatário, canal e referência do aceite. Produção, validação e entrega continuam separadas até o encerramento.

A barra **Esteira guiada** mostra `Plano → Aprovação VP → Ativação → Execução → Entrega` e a próxima ação de cada papel. Esconder controles reduz o ruído, mas a autorização real permanece na API.

O **Painel do VP** consolida sua fila em `Plano → Qualidade → Entregáveis → Entrega`. Aprovações genéricas não decidem `service_deliverable`: esse recurso só pode ser decidido pelo endpoint versionado do entregável, que atualiza aprovação, revisão, status e ledger na mesma transação. Todo comentário de decisão é obrigatório.

## Liberação baseada em evidência

`GET /api/v1/service-catalog/versions/2.0/readiness` separa:

- `internal_assisted_pilot_ready`: as oito ofertas entregues e aceitas, dois ciclos do AI Office e todos os relatórios internos aprovados;
- `market_ready`: torna-se verdadeiro somente depois do readiness interno e de três relatórios reais adicionais: `real_canary`, `operational_slo` e `external_user_validation`.

Na onda multi-tenant, o readiness agrega somente resultados dos tenants em que o operador autenticado possui membership ativa. Cada tenant é consultado em uma sessão RLS própria; a resposta combinada contém apenas estados, artifacts autorizados e a contagem de tenants, sem payload de outro cliente. Assim, as oito ofertas podem ser homologadas entre os Tenants A/B/C sem exigir uma cópia artificial de todas elas em um único tenant.

Os relatórios obrigatórios são `catalog`, `multi_service`, `load`, `resilience`, `usability_owner`, `usability_vp`, `backup_restore`, `sandbox`, `editable_formats` e um `offering_<codigo>` para cada oferta. Eles são Markdown tenant-scoped, imutáveis, com evidências e métricas:

```http
POST /api/v1/service-catalog/versions/2.0/evidence
Idempotency-Key: portfolio-validation-unique-key
Content-Type: application/json

{
  "report_kind": "multi_service",
  "status": "passed",
  "content_markdown": "# Onda concorrente\n\nEvidências e resultados...",
  "evidence_refs": ["temporal:...", "artifact:..."],
  "metrics": {"global_active": 5, "queued": 1, "cross_tenant_leaks": 0}
}
```

`usability_owner` só pode ser registrado pelo owner; `usability_vp`, pelo `engagement_manager`. Registrar um relatório não promove a versão. A promoção requer `POST /api/v1/service-catalog/versions/2.0/decision`, owner autenticado, comentário e readiness completo.

Canário e SLO operacional só podem ser registrados pelo owner. A validação de
usuários externos deve ser revisada e registrada pelo `engagement_manager`.
Ausência ou falha de qualquer um desses três artifacts mantém `market_ready`
falso; uma afirmação do modelo não satisfaz o gate.

O agregador final de liberação é executado por:

```bash
make production-e2e-check
```

Ele exige seis relatórios de carga em duração integral, Playwright JSON sem
skip/flaky/failure e o endpoint de readiness com gates interno e de mercado
verdes. Para executar toda a rodada autorizada, incluindo provider real e soak
de oito horas, use `make production-e2e-execute` com as variáveis descritas em
`docs/local_testing.md`. O comando nunca cria evidência humana nem promove o
catálogo.

## Homologação

Carga autorizada, somente em alvo explicitamente preparado:

```bash
export ASF_LOAD_BEARER_TOKEN='token-temporario'
export ASF_LOAD_TENANT_ID='tenant-de-homologacao'
python scripts/portfolio-load-test.py --profile baseline-2
python scripts/portfolio-load-test.py --profile load-20
python scripts/portfolio-load-test.py --profile load-50
python scripts/portfolio-load-test.py --profile stress-200
python scripts/portfolio-load-test.py --profile spike-500
python scripts/portfolio-load-test.py --profile soak-20
```

O soak usa 20 usuários por oito horas. `--duration-scale` serve apenas para smoke do harness e não satisfaz o gate de oito horas. O script não envia evidência nem aprova resultado; gera Markdown/JSON em `artifacts/portfolio-v2/load/`.

Matriz mínima de falhas:

| Falha injetada | Evidência exigida |
|---|---|
| provider 429 | backoff limitado, tentativa e custo persistidos |
| timeout/schema inválido | falha/retry limitado, item bloqueado ao esgotar |
| restart da API/worker | retomada Temporal sem slot órfão ou output duplicado |
| atraso Temporal | comando no outbox e recuperação dentro do RTO |
| sandbox timeout | gate falho, artifact e bloqueio da entrega |
| ferramenta negada | negação auditada, sem shell ou escalada automática |
| backup/restore | RPO zero para output confirmado e RTO p95 ≤ 5 minutos |

Usabilidade ocorre em duas sessões independentes. O owner executa operação, execução e recovery; o VP executa priorização, aprovação e entrega. Aceite: 100% das tarefas críticas, zero P0/P1 e SEQ mediano ≥ 5/7. Resultado humano não pode ser substituído por teste automatizado.

## Estado deste corte

O runtime, catálogo, UI e harness estão implementados. O primeiro planejamento do case real foi concluído pelo caminho API → LiteLLM → OpenRouter e persistiu plano, uso, custo e eventos; ele permanece deliberadamente em `awaiting_approval`. A versão 2.0 continua candidata porque ainda faltam a execução e entrega desse case, as oito ofertas, a onda completa, falhas production-like, o soak de oito horas e as duas sessões humanas.

## Primeiro caso real

O primeiro caso operacional é o `Opportunity-to-Proposal Copilot`, usado pelo owner e pelo VP para qualificar oportunidades, recomendar uma das oito ofertas e preparar uma proposta editável com four-eyes. A especificação, o dataset controlado e a rubrica ficam em [`homologation/cases/portfolio-v2/commercial-opportunity-copilot`](../homologation/cases/portfolio-v2/commercial-opportunity-copilot/README.md).

A matriz comercial mínima fica em
[`commercial-operation-matrix.json`](../homologation/cases/portfolio-v2/commercial-operation-matrix.json).
Ela prova dois contratos independentes e concorrentes: `AI Value Discovery`
para a AtlasLog, encerrado com diagnóstico e roadmap editáveis sem exigir
código; e `AI Use Case Pilot` para a MetalQuote, um MVP de orçamentação
agêntica que exige código-fonte, `FileChange` com diff, testes unitários,
integrados e E2E, 17 gates, HRS ≥ 90, Ponytail/Cavekit terminais e pacote
versionado. Os tenants não possuem dependência nem reutilização cruzada.

Além da classificação, a homologação de produção agentic usa oito jornadas
realistas, uma por oferta. Cada jornada contém contexto de cliente, fatos
autorizados, termos que tornam o material específico, alegações proibidas,
uma tentativa de prompt injection e uma ficha do sistema de IA com decisão
suportada, grounding, controles humanos, falhas e limites de autonomia. O validador
`scripts/evaluate-agentic-journeys.py` exige por cenário uma jornada completa e
duas repetições provider-real do entregável-probe, cobertura de todos os
entregáveis e modos na jornada completa, estabilidade mínima de 80%,
trilha completa dos agentes, métricas derivadas de qualidade, grounding,
segurança, controle humano, latência e custo, four-eyes, ledger terminal e, nos
fluxos técnicos, 17 gates, HRS mínimo 90 e Ponytail/Cavekit terminais.

O case comercial usa 24 inputs, oito adversariais e rótulos held-out. A base de
conhecimento recebe somente os inputs sem resposta; `scripts/evaluate-commercial-ai-case.py`
mantém os rótulos fora do contexto, exige três rodadas provider-real e deriva
acurácia, segurança, custo, latência, erro de provider e integridade da cadeia
agentic antes de encaminhar a decisão ao VP.

Uma revisão do Portfólio 2.0 não chega ao gate do VP se não cumprir o contrato
estrutural do template. O backend calcula e persiste a avaliação junto da
revisão: seções obrigatórias, substância, evidências tenant-scoped, claims,
riscos, próximos passos, ausência de placeholders e distinção contra
entregáveis pares. Essa avaliação não aprova conteúdo e não substitui a
decisão humana.

O runner usa somente as APIs públicas, é retomável e separa as identidades:

```bash
python scripts/run-portfolio-homologation-case.py validate
python scripts/run-portfolio-homologation-case.py bootstrap
python scripts/run-portfolio-homologation-case.py plan
python scripts/run-portfolio-homologation-case.py approve
python scripts/run-portfolio-homologation-case.py activate
python scripts/run-portfolio-homologation-case.py queue --confirm QUEUE_REAL_PROVIDER_WORK
```

O comando pago não inicia sem a confirmação literal. Revisão, checks, demonstração, usabilidade e entrega continuam manuais e auditáveis.

O Playwright E2E exige Web, API e Keycloak/OIDC ativos. A suíte autenticada inclui uma identidade exclusiva `engagement_manager`, confirma a navegação reduzida, a justificativa obrigatória e a ausência de controles de owner, mas nunca clica na aprovação do case real. O resultado automatizado valida a interface e o RBAC; não substitui a sessão humana de usabilidade nem a decisão do VP.
