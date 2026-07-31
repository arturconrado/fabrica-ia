# Architecture

The factory is a local-first monorepo with an explicit homologation profile and a gated production profile. Production combines FastAPI, PostgreSQL, Temporal, Next.js, Keycloak/OIDC, LiteLLM with OpenRouter/OpenAI upstream, MinIO/S3-compatible storage, MCP allowlisting and Kubernetes sandbox Jobs.

The API owns tenant-scoped operational state: projects, runs, events, agent states, messages, work items, artifacts, files, test reports, quality gates, homologation packages, feedback, learning, knowledge bases, RAG documents/chunks/queries, model calls, MCP invocations, sandbox executions and batch metrics.

The initial deployment is a modular monolith with external adapters. PostgreSQL RLS and automatic ORM scope protect data; tenant/run-prefixed filesystem and S3 keys protect files. A transactional outbox atomically bridges database state to idempotent Temporal start/signal/cancel commands. Temporal owns durable production execution, while each agent step persists a checkpoint, ledger events and evidence before the next handoff.

New technical missions execute `software_factory_ai_native_v2`. A generic graph runner loads the persisted YAML and versioned role prompt/skill, builds a bounded `ContextBundle`, validates `AgentStepResult`, and applies only schema-safe artifact/file operations. `AgentStepExecution`, `ModelCall`, `Artifact` and `FileChange` form the direct provenance chain. The model may request named tool profiles, but only the platform selects and runs exact allowlisted commands in a non-root, network-denied Kubernetes Job. Test truth, budget, 17 gates, HRS and human decisions cannot be overridden by model output.

Migration `0009_ai_cost_governor` adds `AIInvocation` above individual `ModelCall` attempts. Every operational inference has an explicit tenant, journey/resource, correlation key, immutable cost/context policy, projected and actual usage, retry classification and `CostEnvelope`. Insufficient budget pauses the operation and records a ledger decision; it never silently downgrades a protected role. The v2.13 graph is compiled deterministically from the immutable v2.12 graph plus a tracked policy overlay, while the v2.11 baseline remains a frozen benchmark snapshot.

Context v2.13 is assembled by role with reference-type quotas, section views, checksummed tenant-private digests and model-aware tokenization. Stable controls precede task data; the task and Definition of Done are repeated at the end. Role-specific Pydantic schemas remove unused output fields. Initial files remain complete, while review/rework may send validated patches tied to `base_sha256`. Schema-only repair receives only the invalid response and validation error; semantic failure can escalate, while isolation or budget failures never retry.

Migration `0014_compact_unit_context` supports the immutable v2.13.1 candidate. A frozen tenant-scoped `ContextBundle` remains the audit/replay source, while `UnitContextBuilder` emits a bounded provider view containing only goal, constraints, invariants, direct dependency outputs and references selected for that unit. Test failures and decisions are explicit backpropagation evidence for rework. The durable unit stores hashes, the reference manifest and calculated source/sent/saved token counts without creating a cross-tenant response cache. Unit-specific keys and targets stay in the user message; the global role/system prefix remains stable and provider-cache eligible.

Migration `0015_production_plugin_runtime` supports the immutable v2.13.2 policy. The factory pins canonical Ponytail 4.8.4 and Cavekit 4.1.0 adapters that curate only instructions and typed results; they cannot call shell, read secrets, access storage or change workflow authority. Every activation is an idempotent tenant-scoped `PluginInvocation` plus append-only ledger event. Cavekit activations remain `registered` until a validated agent step, execution unit, sandbox report or quality gate supplies a persisted evidence reference; failures are retained and retries must produce evidenced recovery. Ponytail review/debt artifacts are persisted like every other Markdown artifact. Engineer unit descriptors carry requirement, invariant and exact test identifiers, and QA creates `verified_contract` traces only when the declared file exists and an allowlisted test suite passed. The traceability gate rejects round-robin or merely declared links. The native Codex plugin is a developer-host integration; factory missions never execute its lifecycle hooks and instead use the same pinned policy through the internal adapter.

Workflow `2.14.0` is the technical candidate for Portfolio 2.1. It keeps the
same executor and plugin contracts while enforcing path ownership for
Architect, Data Architect, API Contract Engineer, Engineer, QA Engineer,
Security Engineer and DevOps Engineer. Observers cannot write. Every accepted
write requires full content or a patch tied to `base_sha256` and persists a
textual diff, model call, step, author and ledger event. QA authors tests after
implementation; product failures and test-authoring failures follow separate,
bounded edges.

## Durable segmented execution

Migration `0010_durable_segmented_execution` introduces `ExecutionUnit` and `ArtifactFragment`. New runs declare `segmented-output-v1`; historical runs retain their original executor. A short model-produced `NodePlanResult` is frozen before long output. Document roles generate ordered sections, Engineer generates batches of at most four full files, and every segmented node ends with one finalizer. Limits are enforced by Pydantic before provider output can mutate a workspace.

`SoftwareFactoryAINativeWorkflowV2` uses a real activity boundary for planning and for every output unit. Each unit is keyed by `tenant/run/node/iteration/unit/action`, heartbeats while executing, persists its model provenance and can be replayed only with the same descriptor/output hash. A separate assembly checkpoint verifies that every unit is complete, assembles immutable fragments, reconciles files and lets the shared pure `WorkflowTransitionEngine` advance the graph. Inline and Temporal execution therefore share transition, loop and budget rules.

The API, worker and external model cannot form one ACID transaction. Persisted units, artifacts, file-change records and ledger events are exactly-once; an external model response is at-least-once if the worker dies before its call is confirmed. Provider request IDs and invocation identities make that residual repetition observable. Budget pause/resume, operator pause/resume, cancellation and human decisions are Temporal controls, not model decisions.

Migration `0012_llmops_slo` adds cache/readiness telemetry. OpenTelemetry spans correlate workflow, node, unit, invocation, sandbox and gates without prompt contents. Production requires an OTLP HTTP endpoint; API and worker install a batch exporter and the full stack routes it through OpenTelemetry Collector into Tempo, provisioned alongside Prometheus in Grafana. Migration `0013_aggregate_technical_metrics` adds one narrowly scoped `SECURITY DEFINER` function so the non-bypass runtime role can export only aggregate status, duration, retry, token, cache, cost and HRS metrics across the control plane. Its execute privilege is removed from `PUBLIC`, its search path and table references are fixed, and it returns no tenant, run, prompt, artifact or file identifiers. Tenant-scoped APIs calculate detailed SLO evidence and return `insufficient_evidence` instead of treating missing data as success.

Knowledge/RAG follows ADR-0019. Each tenant owns separate bases, documents, chunks and query history under `FORCE ROW LEVEL SECURITY`; production originals use `tenants/{tenant}/knowledge/{base}/`. Recursive semantic-boundary chunking with overlap feeds a versioned hybrid vector/BM25 retriever. Generative answers are opt-in per tenant and never receive excerpts from another tenant.

## Service Delivery OS

Service Delivery OS is a bounded module above the existing factory, not a second orchestration platform. Migration `0008_service_delivery_os` adds three global reference tables (`service_offerings`, `offering_versions`, `agent_templates`) and tenant-scoped engagement, plan, workstream, work-item, deliverable, outcome and Agent Studio tables. Every tenant table uses the same PostgreSQL `FORCE ROW LEVEL SECURITY` contract as runs and knowledge.

The eight offering versions are immutable operational reference data. An `EngagementPlan` adapts one selected version for a contract without modifying its source definition. Plan generation and deliverable drafting use real model calls with schema validation and tenant-scoped context; activation, WIP, pricing, entitlements, approval, delivery, outcome provenance and agent admission remain deterministic human commands.

Critical state changes require idempotency and optimistic `record_version` checks, then append events to the existing ledger. SSE is only a projection refresh signal. The ledger remains authoritative for engagement activation, WIP overrides, revisions, review decisions, delivery, value observations and agent lifecycle decisions.

Agent Studio stores immutable tenant-private agent versions. Global templates contain only abstract skills and policies. A candidate is usable only after allowlist/schema/context/security checks, three benchmark repetitions and human approval. Agents can create content and artifacts through allowlisted capabilities; a tool requirement creates a blocked `tool_gap` for human engineering. Pilot Sprint delegates software generation to `software_factory_ai_native_v2`, preserving the technical executor, its sandbox and the 17 gates.

Migration `0016_service_portfolio_v2` extends this module without creating a second executor. `ServiceCycle`, `ServiceExecution`, `ServiceAcceptanceCheck` and `EngagementDependency` are tenant-scoped and protected by forced RLS. Migration `0017_rls_safe_service_scheduler` adds the narrowly scoped `asf_active_tenant_ids()` control function: it exposes only opaque IDs of active tenants to the non-bypass runtime role, while every workload read and mutation still requires tenant context under forced RLS. `ServiceExecution` is selected by a priority/deadline/round-robin dispatcher, then atomically bridged to Temporal by the same transactional outbox. Active execution rows are the five-global/two-per-tenant service slots; terminal state releases them. A `technical_run` creates a normal AI-native `WorkflowRun`, so its independent ten-global/two-per-tenant `WorkflowSlot`, 17 gates, HRS and Ponytail/Cavekit terminal evidence stay authoritative.

Migration `0018_operator_profiles_and_technical_groups` adds a tenant-scoped
presentation profile to memberships and an `operation_key` to service work
items. Portfolio 2.1 materializes one locked technical operation per contracted
group. A single run/execution/slot fans out to contextualized deliverable
revisions with common technical evidence; retry and cancellation remain group
operations. Professional profiles reorder only equivalent work and never alter
RBAC, tenant scope or deterministic next actions.

Offering v2 snapshots contain versioned display metadata, processes, structured deliverable templates and DoD checks. Human/integration activities wait for external evidence. Deliverable packages are deterministic ZIPs with open sources, applicable Office formats and a SHA-256 manifest. Promotion of v2 remains fail-closed: it requires all offering/cycle checks plus persisted load, resilience, concurrency, usability, restore, sandbox and editability reports; public market readiness remains a separate gate.

## Operational guidance and bounded UI requests

`OperationalGuidance` is an additive projection, not a decision engine. The API
calculates `NextAction` from persisted tenant state and hashes that action with
the relevant versions, executions, revisions, decisions and evidence. Model
output can fill only `why_now`, three bounded checks, three bounded risks, a
draft and confidence; attempts to return an action, URL, resource, priority,
assignee, status or authorization are ignored. Guidance returned with an
existing plan/deliverable model call is linked to that `ModelCall`, the ledger,
`AIActivity` and `AgentRecommendation`. Provider failure uses a deterministic
fallback, and GET/navigation never invokes a model.

Browser reads and session resolution use a 15-second abort signal; commands use
120 seconds. The Next.js BFF allows five additional seconds for transport and
maps upstream aborts to `504 UPSTREAM_TIMEOUT` with a correlation ID. A timed
out command is explicitly outcome-unknown, so the UI refreshes the projection
before allowing a retry. The shared resource hook keeps confirmed data visible
during refresh. SSE loss changes the presentation to a paused state but does
not change the ledger or execution state.

Human decision payloads accept `validation_mode=real|synthetic`. Synthetic
approval is a separate terminal namespace across plans, technical runs, human
gates, packages, deliverables and DoD checks. It can exercise the functional
workflow, but it never promotes client artifacts, completes a real engagement,
updates readiness, or creates a globally eligible learning signal.
