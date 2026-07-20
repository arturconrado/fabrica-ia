import asyncio

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from app.providers.temporal_runner import TemporalWorkflowRunner


def test_temporal_start_is_deduplicated_by_tenant_and_run(monkeypatch):
    calls = []

    class Handle:
        result_run_id = "temporal-run-1"

    class FakeClient:
        async def start_workflow(self, workflow, payload, **kwargs):
            calls.append((workflow, payload, kwargs))
            return Handle()

    async def connect(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(Client, "connect", connect)
    result = asyncio.run(
        TemporalWorkflowRunner().start_enterprise_run(
            tenant_id="tenant-a",
            demand="ContractFlow reference",
            project_id="project-a",
            run_id="run-a",
        )
    )

    workflow, payload, options = calls[0]
    assert workflow == "SoftwareFactoryHomologationWorkflow"
    assert options["id"] == "software-factory-enterprise-tenant-a-run-a"
    assert options["id_conflict_policy"] is WorkflowIDConflictPolicy.USE_EXISTING
    assert payload["run_id"] == "run-a"
    assert result.workflow_id == options["id"]
    assert result.run_id == "temporal-run-1"


def test_temporal_cancel_uses_workflow_cancellation(monkeypatch):
    cancelled = []

    class Handle:
        async def cancel(self):
            cancelled.append(True)

    class FakeClient:
        def get_workflow_handle(self, workflow_id):
            assert workflow_id == "workflow-a"
            return Handle()

    async def connect(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(Client, "connect", connect)
    asyncio.run(TemporalWorkflowRunner().cancel("workflow-a"))
    assert cancelled == [True]


def test_temporal_closed_status_is_observable(monkeypatch):
    class Status:
        name = "COMPLETED"

    class Description:
        status = Status()

    class Handle:
        async def describe(self):
            return Description()

    class FakeClient:
        def get_workflow_handle(self, workflow_id):
            assert workflow_id == "workflow-closed"
            return Handle()

    async def connect(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(Client, "connect", connect)
    assert asyncio.run(TemporalWorkflowRunner().is_workflow_closed("workflow-closed")) is True
