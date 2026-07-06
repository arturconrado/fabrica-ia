# Batch Delivery

Batch delivery is production-only. `POST /batches` creates an enterprise portfolio batch, creates child runs for each item and schedules those runs through Temporal. Item completion, HRS and approval metrics must be validated against the real Temporal worker in the target environment.
