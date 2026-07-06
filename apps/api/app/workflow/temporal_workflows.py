from datetime import timedelta
from typing import Any, Dict

try:
    from temporalio import activity, workflow
except Exception:  # pragma: no cover - imported only by worker with temporal installed
    activity = None
    workflow = None


if activity is not None:

    @activity.defn
    async def execute_enterprise_run_activity(payload: Dict[str, Any]) -> str:
        from app.db.session import SessionLocal
        from app.services.run_service import provider

        db = SessionLocal()
        try:
            run = provider.start_enterprise_run(
                db,
                demand=payload["demand"],
                project_id=payload.get("project_id"),
                tenant_id=payload["tenant_id"],
                run_id=payload.get("run_id"),
            )
            run.temporal_workflow_id = payload.get("temporal_workflow_id") or ""
            run.provider = "production-litellm"
            db.commit()
            return run.id
        finally:
            db.close()


if workflow is not None:

    @workflow.defn(name="SoftwareFactoryHomologationWorkflow")
    class SoftwareFactoryHomologationWorkflow:
        def __init__(self) -> None:
            self._decision: Dict[str, Any] = {}

        @workflow.run
        async def run(self, payload: Dict[str, Any]) -> str:
            run_id = await workflow.execute_activity(
                execute_enterprise_run_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=20),
            )
            await workflow.wait_condition(lambda: bool(self._decision))
            return f"{run_id}:{self._decision.get('decision')}"

        @workflow.signal
        async def human_decision(self, payload: Dict[str, Any]) -> None:
            self._decision = payload

        @workflow.signal
        async def operator_control(self, payload: Dict[str, Any]) -> None:
            if payload.get("action") == "cancel":
                self._decision = {"decision": "cancelled"}
