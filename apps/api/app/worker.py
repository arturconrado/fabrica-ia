import asyncio

from app.core.config import get_settings
from app.db.init_db import init_db
from app.workflow.temporal_workflows import SoftwareFactoryHomologationWorkflow, execute_enterprise_run_activity


async def main() -> None:
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except Exception as exc:  # pragma: no cover - production entrypoint
        raise RuntimeError(f"temporalio is not installed: {exc}") from exc

    settings = get_settings()
    init_db()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[SoftwareFactoryHomologationWorkflow],
        activities=[execute_enterprise_run_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
