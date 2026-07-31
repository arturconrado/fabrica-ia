# Workflow YAML Spec

Workflow YAML contém metadata do grafo, hints de UI, fases, nodes e edges. As definições são persistidas e executadas com evidência de agente/modelo/tool/sandbox.

Desde v2.12, todo node `agent` precisa declarar:

- `max_output_tokens`: teto do node, sempre limitado também pelo alias do modelo;
- `context_policy.version`;
- `allowed_reference_types`;
- `input_budget_tokens`;
- `required_artifacts` e `optional_artifacts`;
- `file_mode`: `none`, `tree`, `diff`, `selected` ou `content`;
- `file_globs` quando o modo é `selected`;
- `max_rag_chunks`, `max_lessons` e `lesson_budget_tokens`.
- `unit_context_mode`: `full` para políticas históricas ou `compact` para seleção determinística por unidade;
- `plan_input_budget_tokens`, `unit_input_budget_tokens` e `finalize_input_budget_tokens`;
- `max_unit_references` e `compact_spec_enabled`;
- `plan_model_role` e `finalize_model_role`: aliases opcionais apenas para manifesto/finalização; o `model_role` do conteúdo crítico permanece autoritativo;
- `minimal_solution_policy`: prioriza reuso e menor implementação suficiente sem permitir a remoção de requisitos ou controles.

Desde a candidata v2.13.2, o overlay pode declarar:

- `plugins.mandatory`, `plugins.fail_closed` e revisões fixadas; atualizações automáticas são proibidas;
- `node_defaults.ponytail_enabled`, `ponytail_mode` (`lite|full|ultra`) e `ponytail_commands`;
- `cavekit_stages`, curados por papel e limitados a `grill|spec|research|review|build|check|backprop|deepen|caveman`;
- em `OutputUnitDescriptor`, `requirement_refs`, `invariant_refs` e `verification_tests` para lotes do Engineer.

Todos os comandos de plugin geram `PluginInvocation` idempotente e evento. Cavekit inicia em `registered`; `completed` exige referência persistida de step, unidade, sandbox ou quality gate, `not_applicable` exige motivo e `failed` exige erro auditável. Ao final de uma missão v2.13.2, nenhuma ativação Cavekit pode permanecer `registered`, e falhas só são aceitas quando uma tentativa posterior do mesmo papel/iteração produz evidência terminal. Os identificadores de especificação são validados contra arquivos persistidos e relatórios de suites allowlisted antes de criar `RequirementTrace` com proveniência `verified_contract`.

Desde a candidata v2.14.0, o overlay também declara:

- `workspace_ownership` por papel, limitado a raízes sob `generated_app/`;
- `candidate_evaluation` com baseline 2.13.2, dataset fixo, três repetições,
  limite de 1,2× para custo/tokens e promoção somente humana;
- `edge_additions` para devoluções limitadas de QA, segurança, Visual QA e
  Accessibility QA ao proprietário do arquivo.

O executor resolve a regra mais específica antes da raiz ampla do Engineer,
valida caminho normalizado e `base_sha256` antes de aplicar conteúdo ou patch e
rejeita conflitos de ownership sem mutar o workspace. Reviewer, Visual QA e
Accessibility QA não possuem paths. Falha de asserção/smoke retorna ao
Engineer; apenas falha de autoria/coleta/sintaxe do próprio teste retorna ao QA,
uma vez. Shell continua limitado aos perfis allowlisted.

O builder falha se um artifact obrigatório estiver ausente. RAG usa chunks do retriever híbrido; documentos completos não são enviados. Artifacts/arquivos estáveis usam digests tenant-private por checksum. `ContextBuild` persiste selecionados, descartados, budgets e motivo de cada referência.
