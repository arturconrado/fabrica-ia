# ADR-0015: Kubernetes Production Profile

## Status
Accepted

## Context
Production needs independent scaling for API, web, workers and sandbox jobs, plus network policy and service integrations.

## Decision
Use Docker Compose for dev-real validation and Kubernetes manifests for production deployment. Managed Postgres, Redis, Temporal, object storage and OIDC may replace bundled services.

## Trade-offs
- Positive: clear path to production isolation and scaling.
- Negative: more operational prerequisites than the MVP.
- Mitigation: keep Compose profile for local validation and document release blockers explicitly.
