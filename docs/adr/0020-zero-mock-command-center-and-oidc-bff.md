# ADR-0020: Zero-mock command center and OIDC BFF

## Status

Accepted

## Context

O piloto assistido precisa operar cinco clientes sem cruzar conhecimento, expor tokens ou apresentar dados fictícios como fatos. Os perfis anteriores aceitavam comportamento determinístico de homologação e a UI exigia múltiplas leituras concorrentes e um token manual.

## Decision

- Perfis operacionais usam LiteLLM e dados persistidos reais; fixtures e provider mock existem somente em `ASF_RUNTIME_PROFILE=test`.
- A web usa OIDC Authorization Code + PKCE por um BFF Next.js. Tokens ficam em cookies HttpOnly e requests recebem tenant apenas no servidor.
- Cada cliente é um tenant com membership, RLS, corpus RAG e objetos próprios. O portfólio calcula resumos em sessões tenant-scoped sem agregar conteúdo.
- A UI inteira usa um command center coerente, projeção segura para reviewer, topologia derivada do YAML e valores ausentes como `null`/estado vazio.
- Artifacts recebem audience e só saem após promoção/package. XP é projeção idempotente do ledger sem autoridade sobre gates.
- Seed operacional, batch fixo e WorkflowCandidate/AFlow stub ficam desabilitados e invisíveis.

## Consequences

- `docker compose up --build` exige onboarding explícito e não cria dataset demonstrativo.
- Endpoints diretos de run são exclusivos do perfil de teste; perfis operacionais passam pelo contrato/entitlement e recusam blueprints sem executor.
- Refresh e logout são centralizados; endpoints mutáveis de auth nunca podem ser prefetched.
- Homologação exige provider real, missão completa e evidência de isolamento, acessibilidade e revisão humana.
