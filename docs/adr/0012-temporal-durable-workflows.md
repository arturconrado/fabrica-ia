# ADR-0012: Temporal For Durable Workflows

## Status
Accepted

## Context
In-process workflow execution cannot guarantee durable pauses, retries or human approval resumption.

## Decision
Add Temporal as the production workflow backend with a worker entrypoint and signal-based human decisions. The local runner remains available for fast deterministic validation.

## Trade-offs
- Positive: durable execution, retries, visibility and resumable human-in-the-loop.
- Negative: operational complexity and worker deployment.
- Mitigation: Docker Compose includes Temporal UI and worker; K8s manifests include worker deployment.
