# ADR-0017: AI-Native MVP Factory

## Status
Superseded in its runtime/mock policy by ADR-0020 and in its executor by ADR-0021

## Context
The factory must validate ideas and build prospect-ready MVPs quickly while preserving deterministic controls for tenant isolation, RBAC, entitlement, ledger integrity, quality gates and human approval.

## Decision
Add `rapid_mvp_factory@1.0` as a contracted component with capabilities for briefing intake, idea validation, MVP scoping, MVP generation, review, proposal generation and package export.

Every critical transition in the prospect-to-MVP flow records an `AIActivity` read model and an `ai.*` event in the append-only ledger. Prompt definitions are versioned as `*@1.0`, use structured output fields, and are seeded with evaluation fixtures. Homologation uses deterministic mock behavior; production providers remain behind the configured LLM gateway.

The operational flow is:

1. Prospect intake.
2. Opportunity creation.
3. AI briefing structure.
4. AI idea validation.
5. AI MVP scope.
6. MVP package generation.
7. Proposal generation.
8. Human approve, reject or request changes.

## Rationale
This makes AI a visible operating layer in the consulting and development process without letting AI override authorization, entitlement, tenant isolation or financial/security controls. The ledger remains the immutable source of truth; AI activity, recommendations and UI timelines are derived operational records.

## Trade-offs
- The Phase 1 generator produces a deterministic homologation package rather than arbitrary code synthesis.
- Prompt evaluations are fixture-based and deterministic; provider-specific quality still requires production-profile validation.
- Pricing is an explainable first-pass estimate, not an automated final commercial approval.

## Consequences
- New MVP factory commands must enforce tenant, RBAC and entitlement before agent work starts.
- Prompt changes require versioned definitions and evaluation fixtures.
- Batch prospect processing must keep tenant leakage and entitlement bypass at zero.
