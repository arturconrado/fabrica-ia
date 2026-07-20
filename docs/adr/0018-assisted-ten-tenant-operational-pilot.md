# ADR-0018: Assisted ten-tenant operational pilot

## Status

Accepted

## Context

The factory must move from feature construction to a controlled commercial-to-delivery line for up to ten assisted clients. Arbitrary LLM code generation would expand operational and security risk before tenant isolation, evidence semantics and recovery are proven.

## Decision

Keep a modular monolith with hexagonal boundaries around workflow, model, sandbox and storage providers. The default path is a deterministic package followed by evaluators, explicit contract/entitlement, a versioned ASF workflow, evidence-backed gates and human approval.

PostgreSQL RLS plus an automatic ORM tenant scope form defense in depth. The append-only ledger uses a per-tenant transaction lock, monotonic head and idempotent command receipts. Local homologation may run one exact allowlisted test command with the mock provider; production requires Temporal, LiteLLM, OIDC, S3 and Kubernetes sandbox.

Tenant onboarding is assisted and capped at 20 users. Pilot configuration caps workflows at ten globally and two per tenant. Production files are mirrored to an isolated S3 prefix per tenant/run, and Temporal starts are deduplicated by deterministic workflow ID. Generative Build, real LLM by default, write-enabled connectors, regulated data and contractual SLA remain disabled.

## Consequences

- The system stays deployable as one API/web unit while external runtime adapters can evolve independently.
- Evidence without a real scanner/test cannot claim a passed technical gate; it remains `review_required` or is classified as declaration/recommendation.
- `docker compose up --build` uses the small deterministic core. Expanded infrastructure is opt-in through the `full` profile.
- Production rollout remains blocked until PostgreSQL RLS/concurrency, authenticated E2E, Docker build and restore drill have executed successfully.
