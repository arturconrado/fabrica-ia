# Batch Delivery

The hard-coded technical `POST /batches` flow is a homologation fixture and is blocked in production because its InventoryFlow and HelpdeskFlow items do not have deterministic blueprint executors. Production currently accepts tenant-scoped prospect intake through `POST /api/v1/prospect-batches`; promotion to ASF runs still follows individual contract, entitlement and blueprint validation.

A production execution batch remains deferred until it has a versioned blueprint per item, Temporal completion reconciliation, fair-capacity behavior and target-stack evidence.
