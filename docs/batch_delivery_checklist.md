# Batch Delivery Checklist

## Production Batch
- [x] Hard-coded `POST /batches` is rejected in production.
- [x] `POST /api/v1/prospect-batches` requires an authenticated tenant operator and creates tenant-scoped intake records.
- [x] Individual promotion still requires proposal approval, contract, entitlement and a supported blueprint.
- [ ] Versioned execution-batch blueprint is not enabled for the assisted pilot.

## Required Release Validation
- [ ] `make docker-full-up` starts the full Docker + kind stack before batch validation.
- [ ] `make vps-docker-up` starts the VPS production Docker stack before external batch validation.
- [ ] Prospect batch tenant isolation negative test passes on PostgreSQL RLS.
- [ ] A future execution batch proves parent orchestration, child completion, fair capacity and metrics in Temporal.

Last update: assisted-pilot safety cut; hard-coded execution batches disabled in production.
