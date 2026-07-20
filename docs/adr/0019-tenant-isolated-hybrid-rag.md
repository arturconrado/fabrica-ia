# ADR-0019: Tenant-isolated hybrid RAG for the assisted pilot

## Status

Accepted.

## Context

One operator will initially serve five clients. Client documents, retrieved excerpts, questions and generated answers must never cross tenant boundaries. The implementation must remain local-first, fit the existing modular monolith and become testable quickly without adding a separate vector database to the pilot.

## Options considered

| Option | Benefits | Costs |
|---|---|---|
| One shared index with metadata filters | Simple ingestion | A missing filter can leak data; unacceptable for the pilot |
| Physical database/index per client | Strong physical boundary | High operational overhead for five small tenants |
| Tenant-scoped tables with PostgreSQL RLS, application scope and tenant S3 prefixes | Reuses proven controls, simple operations, defense in depth | Requires adversarial tests and disciplined migrations |

## Decision

Knowledge bases, documents, chunks and queries are first-class tenant-scoped records protected by explicit query predicates, automatic ORM scope and PostgreSQL `FORCE ROW LEVEL SECURITY`. Original documents are mirrored only below `tenants/{tenant}/knowledge/{base}/`; no global retrieval cache or cross-tenant collection exists.

Ingestion uses recursive Markdown/paragraph/sentence chunking with overlap. Retrieval combines a versioned hashing vector, BM25-style lexical relevance, title overlap and an exact-match bonus, then returns explainable source scores. This deterministic hybrid retriever is the fast pilot baseline; a semantic embedding provider may replace the hashing vector behind a new index version after target-stack evaluation.

Generative answers are disabled by default. They require explicit tenant opt-in and receive only excerpts retrieved from that tenant. The system prompt treats documents as untrusted data and requires source citations. Document content and raw questions are persisted only in RLS-protected records; the append-only ledger receives hashes and references, not raw customer content.

## Trade-offs

- The baseline has weaker synonym recall than a dedicated semantic embedding model.
- Retrieval scans the tenant's bounded pilot corpus in the application process.
- Documents are immutable in the first cut: replacement means ingesting a new version and archiving the old one, preventing stale embeddings.

These costs are acceptable for five assisted clients and avoid a premature vector service. The first cut caps each tenant at 250 documents and 5 million active characters. Revisit when measured retrieval quality is insufficient, a tenant needs a larger corpus or query latency exceeds the pilot SLO.
