# Learning Layer v2.13

O aprendizado é curado e nunca altera prompts, workflow ou roteamento automaticamente.

## Sinais e privacidade

`LearningSignal` registra feedback/decisão humana, conclusão ou falha de step, confidence, retries, tokens, custo, latência, testes, gates e HRS. Rewards ficam entre `-1` e `1`; rating neutro produz `0`.

O primeiro resultado é sempre uma `LearningLesson` privada do tenant. Para propor promoção global, o extrator local remove secrets, e-mails, UUIDs, URLs, IPs, paths e blocos de código. A tabela cross-tenant guarda somente fingerprint do padrão e pseudônimos HMAC de tenant/run; ela nunca guarda texto, ID ou fato de cliente.

## Promoção

Uma candidata comum exige três runs independentes em pelo menos dois tenants. Bloqueios críticos de segurança podem permanecer como candidata sem esse limiar, mas ainda exigem benchmark e decisão administrativa. Uma política de custo nasce como `LearningCandidate(candidate_type=cost_policy)` e nunca modifica prompts ou roteamento diretamente. O benchmark compara medianas e dispersão de ContractFlow e ServiceDesk, com três repetições na v2.11 congelada e três na v2.13.

Todos os gates precisam passar:

- redução mínima de 40% em tokens e custo;
- schemas 100% válidos e zero exposição cross-tenant;
- os mesmos 17 gates, testes/build/axe/security e HRS não inferior;
- cobertura, citações, retries e rework sem regressão.

`LearningPolicy` é imutável. A aprovação cria uma política em `shadow`; promoções humanas avançam para `internal`, `canary` e somente então `active`. Avançar de internal/canary exige uma missão real ligada à política com model calls, testes e 17 gates aprovados. Rollback manual restaura o ponteiro anterior. Custo acima de 10%, regressão de HRS/gates/model calls ou canário cross-tenant dispara rollback automático; isso não aprova uma nova versão.

Migration `0011_global_learning_registry` separa dois catálogos. `learning_policies` continua tenant-private. `global_learning_policies` não possui `tenant_id` e aceita somente regra, rubrica, estratégia de contexto ou correção abstrata com evidência determinística de sanitização. A aplicação de uma política global ocorre por `global_learning_deployments`, que possui RLS e um ponteiro por tenant nos estágios `shadow → internal → canary → active`.

A precedência efetiva é fixa: controles da plataforma/workflow → política global aprovada e ativa no tenant → lesson/política privada aprovada → contexto da tarefa. Nenhuma camada de learning pode alterar gates, HRS, segurança, budget, permissões ou isolamento. Runs antigas preservam a versão efetiva usada. Rollback restaura somente o deployment anterior; nenhuma política é editada ou promovida automaticamente.

## Operação

- `GET /learning/signals`
- `GET /learning/candidates`
- `POST /learning/lessons/{id}/propose-global`
- `POST /learning/candidates/{id}/evaluate`
- `POST /learning/candidates/{id}/decisions`
- `GET /learning/policies`
- `POST /learning/policies/{id}/rollback`
- `POST /learning/policies/{id}/promote-stage`
- `POST /learning/cost-policies/proposals`
- `GET /api/v1/learning/effective-policy`
- `GET /api/v1/admin/global-learning/policies`
- `POST /api/v1/admin/global-learning/candidates/{id}/promote`
- `POST /api/v1/admin/global-learning/policies/{id}/deployments`
- `POST /api/v1/admin/global-learning/deployments/{id}/rollback`

As rotas legadas `/learning/lessons` e `/learning/reward-signals` permanecem compatíveis. A definição histórica está em `benchmarks/workflows/software_factory_ai_native_v2_11.yaml`; o protocolo v2.13 está em `benchmarks/optimization_v2_13.yaml`. A avaliação também exige atribuição de planejamento de engajamento, entregável, RAG, geração e avaliação de agentes em dois tenants. Ela retorna `blocked`, sem skip ou resultado fictício, enquanto a baseline e as runs candidatas reais não existirem.
