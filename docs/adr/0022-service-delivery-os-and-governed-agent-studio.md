# ADR-0022 — Service Delivery OS and governed Agent Studio

Status: accepted
Date: 2026-07-20

## Context

The software factory already owns contracted technical runs, tenant-isolated knowledge, an append-only ledger, provenance, sandbox execution, 17 gates and human approval. Operating five clients also requires service engagements, commitments, business deliverables, capacity and reusable specialist agents. Building a separate service platform or allowing agents to extend themselves would duplicate tenancy/orchestration and weaken the existing controls.

## Decision

Add Service Delivery OS as a module in the FastAPI/Next.js modular monolith. Reuse PostgreSQL RLS, OIDC memberships, contracts/entitlements, the event ledger, ModelGateway, RAG and the v2.12 technical executor.

The global catalog contains eight immutable offering versions and sanitized agent templates. Client adaptations live in tenant-scoped engagements and versioned plans. Activation requires an active contract, entitlements and a human-approved plan. It materializes workstreams, deliverables, work items and an initial team composed only of approved agents.

Global and per-tenant WIP limits are deterministic. Deliverable revisions may be AI-assisted, but submission, approval and delivery are distinct human commands. Outcome metrics always include provenance and source references.

Agent candidates are tenant-private. Generation is limited to prompts, skill definitions, schemas and context policies. Admission requires allowlisted tools, forbidden-action controls, three benchmark repetitions and human approval. A request for a new executable tool becomes a blocked tool gap. Global promotion is a later, independent sanitized process.

`AI Use Case Pilot Sprint` maps to the existing `rapid_mvp_factory` capability and delegates software generation to `software_factory_ai_native_v2`; Service Delivery OS does not replace Temporal, the sandbox or technical quality gates.

## Consequences

- One tenancy, authorization, ledger and provenance model covers consulting services and technical delivery.
- A fresh database contains reference catalog definitions but no fictitious clients or operations.
- Critical transitions require idempotency and optimistic version checks.
- The operator gets a five-client portfolio without aggregating RAG, artifacts or business records.
- AI accelerates planning and content while authority remains deterministic and human-governed.
- Migration `0008_service_delivery_os` is additive, and a feature flag can disable the new module without disabling historical factory runs.

## Rejected alternatives

- A separate service-delivery microservice: premature operational and consistency cost for the five-client pilot.
- Automatic prompt/agent promotion: conflicts with evidence, tenant privacy and human approval requirements.
- Global client knowledge or shared agent memory: violates the tenant isolation contract.
- Treating the service catalog as demo seed: reference definitions are versioned product policy; runtime client records remain empty.
