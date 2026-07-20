# Scaling Strategy

The assisted pilot is deliberately capped at 10 tenants, 20 users per tenant, 10 concurrent workflows globally and 2 per tenant. Production execution already runs in a Temporal worker with PostgreSQL RLS, tenant/run-prefixed S3 storage and Kubernetes sandbox Jobs.

Scale only after the target-stack gates pass. Temporal commands already cross the database boundary through a leased transactional outbox. The next increments are per-agent Temporal activities, dedicated deterministic blueprint executors, managed database/object storage, worker autoscaling and measured capacity tests. Raising limits must preserve fair scheduling, ledger ordering, tenant isolation and RPO/RTO evidence.
