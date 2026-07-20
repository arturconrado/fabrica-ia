import asyncio
from datetime import timedelta
from typing import Any, Dict

try:
    from temporalio import activity, workflow
    from temporalio.common import RetryPolicy
except Exception:  # pragma: no cover - imported only by worker with temporal installed
    activity = None
    workflow = None
    RetryPolicy = None


if activity is not None:

    @activity.defn(name="load_execution_plan")
    async def load_execution_plan_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        def load() -> Dict[str, Any]:
            import yaml

            from app.agents.ai_native_contracts import output_strategy_for_node
            from app.db.session import SessionLocal, set_tenant_context
            from app.models import AgentRunState, ExecutionUnit, WorkflowDefinition, WorkflowRun

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                run = db.query(WorkflowRun).filter_by(id=payload["run_id"], tenant_id=payload["tenant_id"]).first()
                if not run:
                    raise RuntimeError("AI-native Temporal run is missing")
                definition_query = db.query(WorkflowDefinition).filter_by(
                    tenant_id=run.tenant_id, workflow_id=run.workflow_id
                )
                pinned = str((run.context_manifest_json or {}).get("workflow_version") or "")
                if pinned:
                    definition_query = definition_query.filter(WorkflowDefinition.version == pinned)
                definition = definition_query.order_by(WorkflowDefinition.created_at.desc()).first()
                if not definition:
                    raise RuntimeError("Persisted AI-native workflow definition is missing")
                graph = (yaml.safe_load(definition.yaml_content) or {}).get("graph") or {}
                node = next((item for item in graph.get("nodes") or [] if str(item.get("id")) == run.current_node), {})
                units = db.query(ExecutionUnit).filter_by(
                    tenant_id=run.tenant_id, run_id=run.id, node_id=run.current_node
                ).order_by(ExecutionUnit.order_index.asc()).all()
                control = db.query(AgentRunState).filter_by(
                    tenant_id=run.tenant_id, run_id=run.id, agent_name="RUN_CONTROL"
                ).first()
                return {
                    "run_id": run.id,
                    "status": run.status,
                    "current_node": run.current_node,
                    "current_phase": run.current_phase,
                    "strategy": output_strategy_for_node(run.current_node),
                    "node_type": str(node.get("type") or ""),
                    "timeout_seconds": int(node.get("timeout_seconds") or 3600),
                    "required_profiles": list(node.get("allowed_tools") or []),
                    "execution_unit_ids": [unit.id for unit in units],
                    "terminal": run.current_node == "FINAL" or run.status in {"approved", "rejected", "cancelled", "failed"},
                    "waiting_for_human": run.status == "waiting_for_human" or run.current_node == "Human Approval",
                    "operator_paused": bool(control and control.status == "paused"),
                    "budget_paused": run.current_phase == "budget_paused",
                }
            finally:
                db.close()

        return await asyncio.to_thread(load)

    async def _execute_one_node(payload: Dict[str, Any]) -> Dict[str, Any]:
        def execute() -> Dict[str, Any]:
            from app.db.session import SessionLocal, set_tenant_context
            from app.services.run_service import provider

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                if not hasattr(provider, "execute_temporal_ai_native_node"):
                    raise RuntimeError("Configured provider has no AI-native node activity adapter")
                initial_node = str(payload.get("current_node") or "")
                run = provider.execute_temporal_ai_native_node(
                    db,
                    tenant_id=payload["tenant_id"],
                    run_id=payload["run_id"],
                    temporal_workflow_id=payload.get("temporal_workflow_id") or "",
                    expected_node=initial_node,
                )
                from app.models import ExecutionUnit

                units = db.query(ExecutionUnit).filter_by(
                    tenant_id=payload["tenant_id"], run_id=payload["run_id"], node_id=initial_node
                ).order_by(ExecutionUnit.order_index.asc()).all()
                return {
                    "run_id": run.id,
                    "status": run.status,
                    "current_node": run.current_node,
                    "current_phase": run.current_phase,
                    "completed_node": initial_node,
                    "execution_unit_ids": [unit.id for unit in units],
                }
            finally:
                db.close()

        stopped = asyncio.Event()

        async def heartbeat() -> None:
            while not stopped.is_set():
                activity.heartbeat({"run_id": payload.get("run_id"), "node": payload.get("current_node")})
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=20)
                except asyncio.TimeoutError:
                    continue

        task = asyncio.create_task(heartbeat())
        try:
            return await asyncio.to_thread(execute)
        except Exception as exc:
            message = str(exc).casefold()
            if "budget" in message or "tenant" in message and "isolation" in message:
                from temporalio.exceptions import ApplicationError

                raise ApplicationError(str(exc), non_retryable=True, type="budget_or_isolation") from exc
            raise
        finally:
            stopped.set()
            await task

    async def _run_checkpoint_with_heartbeat(
        payload: Dict[str, Any], action: str, operation
    ) -> Dict[str, Any]:
        stopped = asyncio.Event()

        async def heartbeat() -> None:
            while not stopped.is_set():
                activity.heartbeat(
                    {
                        "run_id": payload.get("run_id"),
                        "node": payload.get("node_id") or payload.get("current_node"),
                        "execution_unit_id": payload.get("execution_unit_id"),
                        "action": action,
                    }
                )
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=20)
                except asyncio.TimeoutError:
                    continue

        task = asyncio.create_task(heartbeat())
        try:
            return await asyncio.to_thread(operation)
        finally:
            stopped.set()
            await task

    def _checkpoint_error_kind(exc: Exception) -> str:
        message = str(exc).casefold()
        if "budget" in message:
            return "budget_paused"
        if "tenant" in message and "isolation" in message:
            from temporalio.exceptions import ApplicationError

            raise ApplicationError(str(exc), non_retryable=True, type="budget_or_isolation") from exc
        if "exhausted" in message and "retry limit" in message:
            from temporalio.exceptions import ApplicationError

            raise ApplicationError(str(exc), non_retryable=True, type="unit_retry_exhausted") from exc
        return ""

    def _persist_budget_pause(payload: Dict[str, Any], exc: Exception) -> None:
        from app.db.session import SessionLocal, set_tenant_context
        from app.models import WorkflowRun
        from app.services.run_service import provider

        db = SessionLocal()
        try:
            set_tenant_context(db, payload["tenant_id"])
            run = db.query(WorkflowRun).filter_by(
                id=payload["run_id"], tenant_id=payload["tenant_id"]
            ).first()
            if run:
                provider.ai_native_executor._pause_for_budget(db, run, str(exc)[:1000])
        finally:
            db.close()

    @activity.defn(name="execute_atomic_node")
    async def execute_atomic_node_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("strategy") != "atomic":
            raise RuntimeError("atomic activity received a segmented node")
        return await _execute_one_node(payload)

    @activity.defn(name="plan_segmented_node")
    async def plan_segmented_node_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("strategy") not in {"segmented_artifact", "segmented_workspace"}:
            raise RuntimeError("segmented activity received an atomic node")
        def plan() -> Dict[str, Any]:
            from app.db.session import SessionLocal, set_tenant_context
            from app.services.run_service import provider

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                return provider.plan_temporal_ai_native_node(
                    db,
                    tenant_id=payload["tenant_id"],
                    run_id=payload["run_id"],
                    temporal_workflow_id=payload.get("temporal_workflow_id") or "",
                    expected_node=payload["current_node"],
                )
            finally:
                db.close()

        try:
            return await _run_checkpoint_with_heartbeat(payload, "plan", plan)
        except Exception as exc:
            if _checkpoint_error_kind(exc) == "budget_paused":
                await asyncio.to_thread(_persist_budget_pause, payload, exc)
                return {"run_id": payload["run_id"], "status": "budget_paused", "execution_unit_ids": []}
            raise

    @activity.defn(name="execute_output_unit")
    async def execute_output_unit_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        def execute() -> Dict[str, Any]:
            from app.db.session import SessionLocal, set_tenant_context
            from app.services.run_service import provider

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                return provider.execute_temporal_ai_native_unit(
                    db,
                    tenant_id=payload["tenant_id"],
                    run_id=payload["run_id"],
                    expected_node=payload["node_id"],
                    execution_unit_id=payload["execution_unit_id"],
                )
            finally:
                db.close()

        try:
            return await _run_checkpoint_with_heartbeat(payload, "execute_unit", execute)
        except Exception as exc:
            if _checkpoint_error_kind(exc) == "budget_paused":
                await asyncio.to_thread(_persist_budget_pause, payload, exc)
                return {
                    "run_id": payload["run_id"],
                    "execution_unit_id": payload["execution_unit_id"],
                    "status": "budget_paused",
                }
            raise

    @activity.defn(name="assemble_artifact")
    async def assemble_artifact_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        def assemble_and_transition() -> Dict[str, Any]:
            from app.db.session import SessionLocal, set_tenant_context
            from app.services.run_service import provider

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                run = provider.execute_temporal_ai_native_node(
                    db,
                    tenant_id=payload["tenant_id"],
                    run_id=payload["run_id"],
                    temporal_workflow_id=payload.get("temporal_workflow_id") or "",
                    expected_node=payload["node_id"],
                    finalize_segmented_only=True,
                )
                return {
                    "run_id": run.id,
                    "completed_node": payload["node_id"],
                    "current_node": run.current_node,
                    "current_phase": run.current_phase,
                    "status": run.status,
                }
            finally:
                db.close()

        try:
            return await _run_checkpoint_with_heartbeat(payload, "assemble", assemble_and_transition)
        except Exception as exc:
            if _checkpoint_error_kind(exc) == "budget_paused":
                await asyncio.to_thread(_persist_budget_pause, payload, exc)
                return {"run_id": payload["run_id"], "status": "budget_paused"}
            raise

    @activity.defn(name="run_sandbox_profile")
    async def run_sandbox_profile_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        # Profiles execute inside the node checkpoint and are persisted before
        # this reconciliation boundary returns.
        return {"node_id": payload["node_id"], "status": "reconciled"}

    @activity.defn(name="evaluate_quality")
    async def evaluate_quality_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        def verify() -> Dict[str, Any]:
            from app.db.session import SessionLocal, set_tenant_context
            from app.models import QualityGate

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                gates = db.query(QualityGate).filter_by(tenant_id=payload["tenant_id"], run_id=payload["run_id"]).all()
                return {"gate_count": len(gates), "status": "evaluated" if len(gates) == 17 else "pending"}
            finally:
                db.close()

        return await asyncio.to_thread(verify)

    @activity.defn(name="prepare_human_approval")
    async def prepare_human_approval_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"run_id": payload["run_id"], "status": "waiting_for_human"}

    @activity.defn(name="finalize_delivery")
    async def finalize_delivery_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"run_id": payload["run_id"], "decision": payload.get("decision"), "status": "finalized"}

    @activity.defn
    async def execute_enterprise_run_activity(payload: Dict[str, Any]) -> str:
        def mark_activity_started() -> None:
            from app.db.session import SessionLocal, set_tenant_context
            from app.models import WorkflowRun
            from app.services.run_service import provider

            marker_db = SessionLocal()
            try:
                set_tenant_context(marker_db, payload["tenant_id"])
                marker_run = marker_db.query(WorkflowRun).filter_by(
                    id=payload["run_id"], tenant_id=payload["tenant_id"]
                ).first()
                if not marker_run:
                    raise RuntimeError(f"Temporal activity run is missing: {payload['run_id']}")
                control = provider._control_state(marker_db, marker_run)
                control.outputs_json = sorted(set(control.outputs_json or []) | {"temporal_activity_active"})
                marker_db.commit()
            finally:
                marker_db.close()

        def execute() -> str:
            from app.db.session import SessionLocal
            from app.db.session import set_tenant_context
            from app.services.run_service import provider

            db = SessionLocal()
            try:
                set_tenant_context(db, payload["tenant_id"])
                run = provider.execute_temporal_enterprise_run(
                    db,
                    demand=payload["demand"],
                    project_id=payload.get("project_id"),
                    tenant_id=payload["tenant_id"],
                    run_id=payload["run_id"],
                    temporal_workflow_id=payload.get("temporal_workflow_id") or "",
                )
                return run.id
            finally:
                db.close()

        # This durable marker is committed before the provider thread starts.
        # A cancelled workflow with no marker therefore has no hidden thread.
        mark_activity_started()
        stopped = asyncio.Event()

        async def send_heartbeats() -> None:
            while not stopped.is_set():
                activity.heartbeat({"run_id": payload.get("run_id"), "phase": "enterprise_pipeline"})
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=20)
                except asyncio.TimeoutError:
                    continue

        heartbeat_task = asyncio.create_task(send_heartbeats())
        try:
            try:
                return await asyncio.to_thread(execute)
            except Exception as exc:
                detail = getattr(exc, "detail", {})
                if isinstance(detail, dict) and detail.get("code") == "TEMPORAL_PIPELINE_FAILED":
                    from temporalio.exceptions import ApplicationError

                    raise ApplicationError("Temporal production pipeline failed", non_retryable=True) from exc
                raise
        finally:
            stopped.set()
            await heartbeat_task


if workflow is not None:

    @workflow.defn(name="SoftwareFactoryAINativeWorkflowV2")
    class SoftwareFactoryAINativeWorkflowV2:
        def __init__(self) -> None:
            self._decision: Dict[str, Any] = {}
            self._control: Dict[str, Any] = {}

        @workflow.run
        async def run(self, payload: Dict[str, Any]) -> str:
            activity_retry = RetryPolicy(maximum_attempts=3)
            while True:
                plan = await workflow.execute_activity(
                    load_execution_plan_activity,
                    payload,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )
                if plan.get("operator_paused") or plan.get("budget_paused"):
                    await workflow.wait_condition(
                        lambda: self._control.get("action") in {"resume", "cancel"}
                    )
                    action = self._control.get("action")
                    self._control = {}
                    if action == "cancel":
                        return f"{payload['run_id']}:cancelled"
                    continue
                if plan.get("terminal"):
                    return f"{payload['run_id']}:{plan.get('status')}"
                if plan.get("waiting_for_human"):
                    await workflow.execute_activity(
                        prepare_human_approval_activity,
                        payload,
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=activity_retry,
                    )
                    await workflow.wait_condition(lambda: bool(self._decision) or self._control.get("action") == "cancel")
                    if self._control.get("action") == "cancel":
                        return f"{payload['run_id']}:cancelled"
                    decision = dict(self._decision)
                    self._decision = {}
                    if decision.get("decision") == "changes_requested":
                        continue
                    await workflow.execute_activity(
                        finalize_delivery_activity,
                        {**payload, "decision": decision.get("decision")},
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=activity_retry,
                    )
                    return f"{payload['run_id']}:{decision.get('decision')}"

                node_payload = {**payload, **plan}
                node_activity = execute_atomic_node_activity if plan.get("strategy") == "atomic" else plan_segmented_node_activity
                node_result = await workflow.execute_activity(
                    node_activity,
                    node_payload,
                    start_to_close_timeout=timedelta(seconds=max(300, int(plan.get("timeout_seconds") or 3600))),
                    heartbeat_timeout=timedelta(seconds=60),
                    retry_policy=activity_retry,
                )
                if node_result.get("status") == "budget_paused":
                    continue
                refreshed = await workflow.execute_activity(
                    load_execution_plan_activity,
                    payload,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=activity_retry,
                )
                if plan.get("strategy") != "atomic":
                    unit_budget_paused = False
                    for unit_id in node_result.get("execution_unit_ids") or []:
                        unit_result = await workflow.execute_activity(
                            execute_output_unit_activity,
                            {**payload, "node_id": plan.get("current_node"), "execution_unit_id": unit_id},
                            start_to_close_timeout=timedelta(seconds=max(300, int(plan.get("timeout_seconds") or 3600))),
                            heartbeat_timeout=timedelta(seconds=60),
                            retry_policy=activity_retry,
                        )
                        if unit_result.get("status") == "budget_paused":
                            unit_budget_paused = True
                            break
                    if unit_budget_paused:
                        continue
                    assembly_result = await workflow.execute_activity(
                        assemble_artifact_activity,
                        {**payload, "node_id": plan.get("current_node")},
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=activity_retry,
                    )
                    if assembly_result.get("status") == "budget_paused":
                        continue
                if plan.get("required_profiles"):
                    await workflow.execute_activity(
                        run_sandbox_profile_activity,
                        {**payload, "node_id": plan.get("current_node")},
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=activity_retry,
                    )
                if plan.get("current_node") == "Quality Governor":
                    await workflow.execute_activity(
                        evaluate_quality_activity,
                        payload,
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=activity_retry,
                    )

        @workflow.signal
        async def human_decision(self, payload: Dict[str, Any]) -> None:
            self._decision = payload

        @workflow.signal
        async def operator_control(self, payload: Dict[str, Any]) -> None:
            self._control = payload

    @workflow.defn(name="SoftwareFactoryHomologationWorkflow")
    class SoftwareFactoryHomologationWorkflow:
        def __init__(self) -> None:
            self._decision: Dict[str, Any] = {}

        @workflow.run
        async def run(self, payload: Dict[str, Any]) -> str:
            run_id = await workflow.execute_activity(
                execute_enterprise_run_activity,
                payload,
                start_to_close_timeout=timedelta(hours=8),
                schedule_to_close_timeout=timedelta(hours=24),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            while True:
                await workflow.wait_condition(lambda: bool(self._decision))
                decision = dict(self._decision)
                if decision.get("decision") != "changes_requested":
                    return f"{run_id}:{decision.get('decision')}"
                self._decision = {}
                run_id = await workflow.execute_activity(
                    execute_enterprise_run_activity,
                    payload,
                    start_to_close_timeout=timedelta(hours=8),
                    schedule_to_close_timeout=timedelta(hours=24),
                    heartbeat_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )

        @workflow.signal
        async def human_decision(self, payload: Dict[str, Any]) -> None:
            self._decision = payload

        @workflow.signal
        async def operator_control(self, payload: Dict[str, Any]) -> None:
            if payload.get("action") == "cancel":
                self._decision = {"decision": "cancelled"}
