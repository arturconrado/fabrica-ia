# ADR-0016: Service Delivery OS Phase 1 Runtime and Ledger

## Status
Superseded by ADR-0020

## Context
The Agentic Service Delivery OS needs a homologation-ready vertical slice that runs locally without real LLM secrets, while the existing ASF production profile must keep its OIDC, Temporal, S3, sandbox and real LLM requirements. The platform also must avoid competing audit/event sources.

## Decision
Add explicit runtime profiles:

- `homologation + mock + homologation`
- `homologation + litellm + homologation`
- `homologation + mock + temporal`
- `production + litellm + temporal`

All other combinations fail during startup. The default local profile is homologation with deterministic mocks.

Add `ledger_records` as the append-only source of truth for domain events. `audit_projections`, `audit_logs` and `agent_events` are read models/projections derived from ledger writes.

## Rationale
This keeps production controls intact while making `docker compose up --build` useful for pre-production demonstration. It also prevents business commands, audit views and agent timelines from drifting into separate truths.

## Trade-offs
- Homologation can run without real LLM behavior, so provider-specific failures still require production-profile validation.
- Existing `AgentEvent` remains for UI/SSE compatibility, but new code treats it as a projection.

## Consequences
- Domain mutations must append a ledger event in the same unit of work as state changes.
- Projection rebuild and hash-chain integrity are now testable quality gates.
- Production startup validation is stricter and rejects mock providers.
