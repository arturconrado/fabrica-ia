import asyncio

from app.core.config import get_settings, validate_production_runtime
from app.db.init_db import init_db
from app.observability.tracing import configure_tracing, shutdown_tracing
from app.workflow.temporal_workflows import (
    SoftwareFactoryAINativeWorkflowV2,
    SoftwareFactoryHomologationWorkflow,
    assemble_artifact_activity,
    evaluate_quality_activity,
    execute_atomic_node_activity,
    execute_enterprise_run_activity,
    execute_output_unit_activity,
    finalize_delivery_activity,
    load_execution_plan_activity,
    plan_segmented_node_activity,
    prepare_human_approval_activity,
    run_sandbox_profile_activity,
)
from app.workflow.temporal_outbox import run_temporal_outbox_dispatcher


async def main() -> None:
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except Exception as exc:  # pragma: no cover - production entrypoint
        raise RuntimeError(f"temporalio is not installed: {exc}") from exc

    settings = get_settings()
    validate_production_runtime(settings)
    configure_tracing(settings, service_name="agentic-software-factory-worker")
    init_db()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[SoftwareFactoryHomologationWorkflow, SoftwareFactoryAINativeWorkflowV2],
        activities=[
            execute_enterprise_run_activity,
            load_execution_plan_activity,
            execute_atomic_node_activity,
            plan_segmented_node_activity,
            execute_output_unit_activity,
            assemble_artifact_activity,
            run_sandbox_profile_activity,
            evaluate_quality_activity,
            prepare_human_approval_activity,
            finalize_delivery_activity,
        ],
    )
    try:
        await asyncio.gather(worker.run(), run_temporal_outbox_dispatcher())
    finally:
        shutdown_tracing()


if __name__ == "__main__":
    asyncio.run(main())
