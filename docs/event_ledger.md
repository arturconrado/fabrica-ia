# Event Ledger

Events are append-only records. Important run, phase, node, agent, tool, file, artifact, requirement, review, test, quality, approval, feedback, learning, batch and service-delivery actions are persisted.

`ledger_records` is the immutable source of truth. Audit logs, agent events, dashboard activity and AI activity timelines are projections or read models derived from ledger-backed operations.

AI-native MVP factory transitions write `ai.*` ledger events and `AIActivity` read models with prompt code/version, structured output and confidence. Provider tokens, cache and cost are persisted in `ModelCall`/`AIInvocation`; projections are identified separately. These records support UI explanation and auditability, but security enforcement remains deterministic in RBAC, entitlement checks and tenant-scoped repositories.

# Eventos do governador de custo v2.13

Cada inferência operacional cria um agregado `ai_invocation`. Uma execução concluída registra `ai.invocation_recorded`; bloqueio preflight por orçamento registra `ai.invocation_budget_blocked`. A chave de idempotência inclui a invocação e a tentativa persistida. O payload contém somente escopo, política, rota, classificação de retry e uso/custo auditável — nunca prompt, resposta, secret ou chain-of-thought.

# Eventos dos protocolos v2.13.2

Cada aplicação de Ponytail ou Cavekit registra `plugin.{plugin}.{comando}` e uma `PluginInvocation` com versão, revisão, node, unidade, modo, hashes e estado. Para Cavekit, o ledger recebe um evento `registered` e outro na transição terminal baseada em evidência; replays reutilizam a mesma invocação e não duplicam a transição. O payload contém somente metadados e referências técnicas, nunca conteúdo de cliente ou instruções completas.

# Eventos do portfólio de serviços 2.0

Comandos idempotentes registram criação/aprovação de plano, ativação, ciclo, fila, dispatch Temporal, retry, cancelamento, espera por evidência, delegação técnica e término. Revisões, decisões, entrega, checks e restrições externas mantêm identidade, comentário e referências. Pacotes editáveis geram `service_deliverable.package_generated`; relatórios de homologação geram `service_portfolio.validation_recorded`. A promoção da versão gera `service_portfolio.active` somente depois da leitura determinística dessas evidências.
