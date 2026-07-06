# ADR-0013: MCP Allowlisted Tool Gateway

## Status
Accepted

## Context
Agents need external tools, but unrestricted tool execution is unsafe in a multi-tenant factory.

## Decision
Represent MCP tools through tenant-scoped `ToolPolicy` rows. The API only executes allowlisted tools and records invocations. HTTP JSON-RPC gateway execution is supported in-process; richer stdio/SSE transports should run in a dedicated gateway.

## Trade-offs
- Positive: explicit permissions and auditable tool use.
- Negative: fewer transports in the API process.
- Mitigation: keep transport metadata in policy and add dedicated MCP gateway when needed.
