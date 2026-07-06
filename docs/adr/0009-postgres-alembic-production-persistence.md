# ADR-0009: Postgres And Alembic For Production Persistence

## Status
Accepted

## Context
The production-only runtime needs concurrent writes, durable isolation, migrations and operational tooling in every environment.

## Decision
Use PostgreSQL as the database and Alembic as the migration path for local validation, homologation and production.

## Trade-offs
- Positive: safer concurrency, production observability and schema evolution.
- Negative: heavier local stack.
- Mitigation: Docker Compose provides Postgres with the same application contract used in production.
