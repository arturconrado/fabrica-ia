# ADR-0014: Sandboxed Generated Code Execution

## Status
Accepted

## Context
Generated code and tests are untrusted. Running them directly inside the API process is not acceptable for production.

## Decision
Route generated test execution through `SandboxExecutor`. Local backend is development-only; production backend creates Kubernetes Jobs with non-root, read-only root filesystem, resource limits, no service account token and RuntimeClass gVisor/Kata when available.

## Trade-offs
- Positive: command allowlist, isolation and execution evidence.
- Negative: workspace transfer to sandbox jobs needs object storage/PVC integration for production scale.
- Mitigation: record every execution and block release until Kubernetes sandbox is validated in target cluster.
