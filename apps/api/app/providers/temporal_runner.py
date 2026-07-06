import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import get_settings


@dataclass
class TemporalStartResult:
    workflow_id: str
    run_id: str
    status: str


class TemporalWorkflowRunner:
    async def start_enterprise_run(
        self,
        *,
        tenant_id: str,
        demand: str,
        run_id: str,
        project_id: Optional[str] = None,
    ) -> TemporalStartResult:
        settings = get_settings()
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        workflow_id = f"software-factory-enterprise-{tenant_id}-{uuid.uuid4().hex[:12]}"
        handle = await client.start_workflow(
            "SoftwareFactoryHomologationWorkflow",
            {
                "tenant_id": tenant_id,
                "demand": demand,
                "project_id": project_id,
                "run_id": run_id,
                "temporal_workflow_id": workflow_id,
            },
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        return TemporalStartResult(workflow_id=workflow_id, run_id=run_id or handle.result_run_id or "", status="scheduled")

    async def signal(self, workflow_id: str, signal_name: str, payload: Dict[str, Any]) -> None:
        settings = get_settings()
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(signal_name, payload)
