# ADR 0001 - Production-Only Local Environment

## Status
Superseded by production-only release policy.

## Decision
Local development must use the same operational contracts as production: PostgreSQL, Temporal, OIDC, LiteLLM with OpenRouter/OpenAI upstream, S3-compatible storage, MCP allowlisting and Kubernetes sandbox Jobs. Simplified local execution is not an accepted homologation path.
