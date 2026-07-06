# Security

## Current Controls

- Operational routes require a valid OIDC/JWKS principal.
- Projects, runs, events, artifacts, files, tests, quality, feedback, learning and batches are tenant-scoped.
- Mutating routes use RBAC helpers.
- AuditLog records tenant, project, run, feedback, MCP and learning actions.
- Workspace file access uses path traversal protection.
- Generated code tests go through `SandboxExecutor`.
- Sandbox commands are allowlisted; default is `python -m pytest generated_app/tests`.
- Sandbox backend must be Kubernetes and must mount a workspace PVC.
- MCP execution is denied unless a tenant-scoped `ToolPolicy` allowlists the tool.
- MCP invocations, model calls and sandbox executions are persisted.

## Production Requirements

- Configure real OIDC issuer, audience and JWKS URL.
- Use managed or hardened Postgres, Redis, Temporal and object storage.
- Run sandbox workloads in a separate Kubernetes namespace.
- Apply deny-all egress/ingress NetworkPolicy to sandbox namespace.
- Prefer gVisor, Kata or another hardened RuntimeClass for sandbox pods.
- Store secrets in the platform secret manager, not in git.
- Validate tenant isolation with adversarial tests before release.

## Known Gaps Before Production Sign-off

- Kubernetes sandbox workspace PVC/object storage handoff must be validated in the target cluster.
- MCP stdio tools should run in a dedicated gateway for stronger process isolation.
