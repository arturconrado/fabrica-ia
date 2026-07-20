from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import get_settings


@dataclass
class TemporalStartResult:
    workflow_id: str
    run_id: str
    status: str


class TemporalWorkflowRunner:
    @staticmethod
    def workflow_id(tenant_id: str, run_id: str) -> str:
        return f"software-factory-enterprise-{tenant_id}-{run_id}"

    async def start_enterprise_run(
        self,
        *,
        tenant_id: str,
        demand: str,
        run_id: str,
        project_id: Optional[str] = None,
        executor_protocol_version: str = "legacy",
    ) -> TemporalStartResult:
        settings = get_settings()
        try:
            from temporalio.client import Client
            from temporalio.common import WorkflowIDConflictPolicy
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        workflow_id = self.workflow_id(tenant_id, run_id)
        workflow_name = (
            "SoftwareFactoryAINativeWorkflowV2"
            if executor_protocol_version == "segmented-output-v1"
            else "SoftwareFactoryHomologationWorkflow"
        )
        handle = await client.start_workflow(
            workflow_name,
            {
                "tenant_id": tenant_id,
                "demand": demand,
                "project_id": project_id,
                "run_id": run_id,
                "temporal_workflow_id": workflow_id,
                "executor_protocol_version": executor_protocol_version,
            },
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return TemporalStartResult(workflow_id=workflow_id, run_id=handle.result_run_id or "", status="scheduled")

    async def signal(self, workflow_id: str, signal_name: str, payload: Dict[str, Any]) -> None:
        settings = get_settings()
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(signal_name, payload)

    async def cancel(self, workflow_id: str) -> None:
        settings = get_settings()
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()

    async def is_workflow_closed(self, workflow_id: str) -> bool:
        settings = get_settings()
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - production dependency path
            raise RuntimeError(f"temporalio is not installed: {exc}") from exc
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        description = await client.get_workflow_handle(workflow_id).describe()
        return getattr(description.status, "name", str(description.status)).upper() != "RUNNING"
