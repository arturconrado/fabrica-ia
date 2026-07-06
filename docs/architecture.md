# Architecture

The factory is a production-only monorepo with FastAPI, PostgreSQL, Redis, Temporal, Next.js, Keycloak/OIDC, LiteLLM with OpenRouter/OpenAI upstream, MinIO/S3-compatible storage, MCP allowlisting and Kubernetes sandbox Jobs.

The API owns tenant-scoped operational state: projects, runs, events, agent states, messages, work items, artifacts, files, test reports, quality gates, homologation packages, feedback, learning, model calls, MCP invocations, sandbox executions and batch metrics.
