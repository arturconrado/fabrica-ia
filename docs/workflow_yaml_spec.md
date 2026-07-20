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

O builder falha se um artifact obrigatório estiver ausente. RAG usa chunks do retriever híbrido; documentos completos não são enviados. Artifacts/arquivos estáveis usam digests tenant-private por checksum. `ContextBuild` persiste selecionados, descartados, budgets e motivo de cada referência.
