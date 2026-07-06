# Batch Delivery Checklist

## Production Batch
- [x] Public creation endpoint is `POST /batches`.
- [x] Public legacy batch endpoint removed.
- [x] Batch requires authenticated operator/admin/owner.
- [x] Batch and items are tenant-scoped.
- [x] Batch creates enterprise portfolio items.
- [x] Each item creates a child `WorkflowRun`.
- [x] Each child run is scheduled through Temporal.
- [x] Temporal workflow ids are persisted on child runs.
- [x] Initial batch metric `scheduled_runs` is persisted.
- [x] Batch UI starts through `/batches`.
- [x] Batch item and metric list endpoints remain tenant-scoped.

## Required Release Validation
- [ ] `make docker-full-up` starts the full Docker + kind stack before batch validation.
- [ ] `make vps-docker-up` starts the VPS production Docker stack before external batch validation.
- [ ] Parent batch workflow orchestration validated in Temporal target environment.
- [ ] Child workflow completion updates item status and HRS.
- [ ] Item approval signals validated through Temporal.
- [ ] Batch metrics validated after all child runs finish.
- [ ] Batch UI links open child run workspaces.
- [ ] Batch tenant isolation negative test passes.
- [ ] Concurrent batch scheduling tested with production Postgres/Temporal.
- [ ] `make docker-full-validate` confirms `POST /batches`, 3 child items and metrics against the real local stack.
- [ ] `make vps-docker-validate` confirms `POST /batches`, 3 child items and metrics through the public API domain.

Last update: VPS Docker production deployment path.
