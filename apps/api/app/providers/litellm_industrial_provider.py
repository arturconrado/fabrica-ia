import threading
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.agents.production_pipeline_provider import ProductionPipelineProvider
from app.agents.ai_native_executor import AI_NATIVE_WORKFLOW_ID, AINativeWorkflowExecutor
from app.core.config import get_settings
from app.core.status import PENDING, RUNNING, WAITING_FOR_HUMAN
from app.events.event_service import emit_event
from app.models import AgentStepExecution, ApprovalRequest, DecisionRecord, Project, WorkflowRun, utcnow
from app.providers.model_gateway import ModelGateway
from app.providers.cost_governor import AIInvocationScope, CostEnvelope
from app.service_delivery.capacity import acquire_workflow_slot
from app.service_delivery.service import DomainError


class LiteLLMIndustrialAgentProvider(ProductionPipelineProvider):
    def __init__(self) -> None:
        self.gateway = ModelGateway()
        self.ai_native_executor = AINativeWorkflowExecutor(gateway=self.gateway)

    def generate_structured(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.gateway.call(
            db=db,
            tenant_id=tenant_id,
            run_id=run_id,
            agent_name=agent_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are an industrial software factory agent. Return compact JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            response_schema=schema,
            routing_policy_version="legacy-industrial-2.13.0",
            invocation_scope=AIInvocationScope(
                scope_type="factory_run",
                scope_id=run_id,
                correlation_id=run_id,
                policy_version="2.13.0",
                routing_reason="legacy_factory_compatibility",
                envelope=CostEnvelope(
                    soft_budget_usd=get_settings().model_run_budget_usd * 0.8,
                    hard_budget_usd=get_settings().model_run_budget_usd,
                ),
                metadata={"agent_name": agent_name},
            ),
        )

    def start_enterprise_run(
        self,
        db: Session,
        demand: str,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        tenant_id: str = "local-dev",
        run_id: Optional[str] = None,
    ):
        run = super().start_enterprise_run(
            db,
            demand=demand,
            project_id=project_id,
            project_name=project_name,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        run.provider = "production-litellm"
        db.commit()
        db.refresh(run)
        return run

    def _start_node(self, db: Session, run, node_id: str, phase: str, iteration: int = 1, max_iterations: int = 1):
        state = super()._start_node(db, run, node_id, phase, iteration=iteration, max_iterations=max_iterations)
        model_result = self.generate_structured(
            db,
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name=node_id,
            prompt=(
                f"Run demand:\n{run.demand}\n\n"
                f"Agent: {node_id}\nPhase: {phase}\nIteration: {iteration}/{max_iterations}\n"
                "Return a compact JSON object with keys decision, reasoning_summary, output_refs, risks, next_action. "
                "Do not include hidden chain-of-thought."
            ),
            schema={
                "type": "object",
                "required": ["decision", "reasoning_summary", "output_refs", "risks", "next_action"],
            },
        )
        emit_event(
            db,
            run.id,
            "model.call_completed",
            f"{node_id} called the production LiteLLM gateway.",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            tenant_id=run.tenant_id,
            model_call_id=str(model_result["id"]),
            payload={"model": model_result["model"], "provider": "litellm"},
        )
        return state

    def start_ai_native_enterprise_run(
        self,
        db: Session,
        *,
        demand: str,
        project_id: str,
        tenant_id: str,
        context_manifest: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        self.ensure_workflows(db, tenant_id=tenant_id)
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first()
        if not project:
            raise DomainError(404, "PROJECT_NOT_FOUND", "AI-native run requires an existing tenant project")
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project.id,
            workflow_id=AI_NATIVE_WORKFLOW_ID,
            demand=demand,
            status=RUNNING,
            current_phase="demand_classification",
            current_node="Demand Classifier",
            provider="litellm-ai-native-v2",
            generation_mode="ai_native_v2",
            executor_protocol_version="segmented-output-v1",
            trace_id=str(uuid.uuid4()),
            context_manifest_json={
                **(context_manifest or {}),
                "workflow_version": "2.13.0",
                "context_policy_version": "2.13.0",
                "cost_policy_version": "2.13.0",
            },
            ai_budget_usd=get_settings().model_run_budget_usd,
            ai_cost_usd=0.0,
            cost_estimate=0.0,
        )
        db.add(run)
        db.flush()
        acquire_workflow_slot(db, run.id)
        self._seed_agent_operations(db, run)
        emit_event(
            db,
            run.id,
            "run.created",
            f"Run AI-native v2 criada para {project.name}.",
            payload={"generation_mode": "ai_native_v2", "workflow_id": AI_NATIVE_WORKFLOW_ID},
        )
        emit_event(
            db,
            run.id,
            "run.started",
            "Executor AI-native iniciou a linha de produção auditável.",
            payload={"generation_mode": "ai_native_v2"},
        )
        db.commit()
        db.refresh(run)
        self.resume_ai_native_rework(run.id, tenant_id)
        return run

    def resume_ai_native_rework(self, run_id: str, tenant_id: str) -> None:
        thread = threading.Thread(target=self._run_ai_native_background, args=(run_id, tenant_id), daemon=True)
        thread.start()

    def _run_ai_native_background(self, run_id: str, tenant_id: str) -> None:
        from app.db.session import SessionLocal, set_tenant_context

        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
            if run:
                self.ai_native_executor.execute(db, run=run, provider=self)
        finally:
            db.close()

    def execute_temporal_enterprise_run(
        self,
        db: Session,
        *,
        demand: str,
        project_id: Optional[str],
        tenant_id: str,
        run_id: str,
        temporal_workflow_id: str,
        expected_node: str = "",
    ) -> WorkflowRun:
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
        if not run or run.workflow_id != AI_NATIVE_WORKFLOW_ID or run.generation_mode != "ai_native_v2":
            return super().execute_temporal_enterprise_run(
                db,
                demand=demand,
                project_id=project_id,
                tenant_id=tenant_id,
                run_id=run_id,
                temporal_workflow_id=temporal_workflow_id,
            )
        self.ensure_workflows(db, tenant_id=tenant_id)
        run.temporal_workflow_id = temporal_workflow_id
        run.provider = "litellm-ai-native-v2"
        run.status = RUNNING
        run.finished_at = None
        acquire_workflow_slot(db, run.id)
        if not db.query(DecisionRecord).filter_by(
            tenant_id=tenant_id,
            run_id=run.id,
            title="AI-native v2 execution",
        ).first():
            db.add(
                DecisionRecord(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    run_id=run.id,
                    node_id="USER",
                    title="AI-native v2 execution",
                    decision="Use model outputs as direct artifact and workspace inputs after schema validation.",
                    rationale="The contracted scope requires real generative delivery with deterministic controls.",
                    alternatives_json=["deterministic_v1 retained only for historical runs"],
                )
            )
        self._seed_agent_operations(db, run)
        db.commit()
        executed = self.ai_native_executor.execute(db, run=run, provider=self)
        if executed.status == "failed":
            raise DomainError(500, "TEMPORAL_PIPELINE_FAILED", "AI-native Temporal pipeline failed")
        return executed

    def execute_temporal_ai_native_node(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        temporal_workflow_id: str,
        expected_node: str = "",
        finalize_segmented_only: bool = False,
    ) -> WorkflowRun:
        """Execute at most one workflow node; Temporal owns the durable outer loop."""

        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
        if not run or run.workflow_id != AI_NATIVE_WORKFLOW_ID or run.generation_mode != "ai_native_v2":
            raise RuntimeError("AI-native Temporal node activity requires a compatible persisted run")
        if expected_node and run.current_node != expected_node:
            # The previous attempt committed the transition but Temporal did
            # not receive its response. Reconcile instead of executing the
            # next node under the stale activity identity.
            return run
        run.temporal_workflow_id = temporal_workflow_id
        run.provider = "litellm-ai-native-v2"
        run.status = RUNNING
        run.finished_at = None
        acquire_workflow_slot(db, run.id)
        db.commit()
        return self.ai_native_executor.execute(
            db,
            run=run,
            provider=self,
            max_nodes=1,
            segmented_finalize_only=finalize_segmented_only,
        )

    def plan_temporal_ai_native_node(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        temporal_workflow_id: str,
        expected_node: str,
    ) -> dict:
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
        if not run or run.current_node != expected_node:
            raise RuntimeError("Segmented planning checkpoint no longer matches the active run node")
        run.temporal_workflow_id = temporal_workflow_id
        run.provider = "litellm-ai-native-v2"
        run.status = RUNNING
        acquire_workflow_slot(db, run.id)
        db.commit()
        return self.ai_native_executor.plan_temporal_segmented_node(db, run=run)

    def execute_temporal_ai_native_unit(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        expected_node: str,
        execution_unit_id: str,
    ) -> dict:
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
        if not run or run.current_node != expected_node:
            raise RuntimeError("Output unit checkpoint no longer matches the active run node")
        return self.ai_native_executor.execute_temporal_output_unit(
            db, run=run, execution_unit_id=execution_unit_id
        )

    def request_changes(self, db: Session, run_id: str, comment: str = "", *, commit: bool = True) -> WorkflowRun:
        run = db.get(WorkflowRun, run_id)
        if not run or run.workflow_id != AI_NATIVE_WORKFLOW_ID or run.generation_mode != "ai_native_v2":
            return super().request_changes(db, run_id, comment, commit=commit)
        if not comment.strip():
            raise DomainError(400, "CHANGES_COMMENT_REQUIRED", "Requested changes require a human comment")
        if run.status != WAITING_FOR_HUMAN:
            raise DomainError(409, "RUN_NOT_AWAITING_APPROVAL", "Run is not awaiting final human review")
        prior = db.query(DecisionRecord).filter_by(
            tenant_id=run.tenant_id,
            run_id=run.id,
            title="Human requested AI-native rework",
        ).count()
        if prior >= 2:
            raise DomainError(409, "REWORK_LIMIT_EXCEEDED", "AI-native human rework is limited to two iterations")
        approval = (
            db.query(ApprovalRequest)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, status=PENDING)
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        if not approval:
            raise DomainError(409, "APPROVAL_NOT_PENDING", "A pending approval request is required")
        approval.status = "changes_requested"
        approval.human_comment = comment.strip()
        approval.resolved_at = utcnow()
        decision_record = DecisionRecord(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id="Human Approval",
                title="Human requested AI-native rework",
                decision=comment.strip(),
                rationale="Explicit reviewer feedback becomes scoped context for the next Engineer iteration.",
                alternatives_json=["approve", "reject"],
            )
        db.add(decision_record)
        latest_engineer_step = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id="Engineer")
            .order_by(AgentStepExecution.iteration.desc())
            .first()
        )
        next_engineer_iteration = int(latest_engineer_step.iteration if latest_engineer_step else 0) + 1
        run.context_manifest_json = {
            **(run.context_manifest_json or {}),
            "resume": {
                "node": "Engineer",
                "iteration": next_engineer_iteration,
                "decision_record_id": decision_record.id,
            },
        }
        run.status = RUNNING
        run.current_phase = "implementation"
        run.current_node = "Engineer"
        run.finished_at = None
        acquire_workflow_slot(db, run.id)
        emit_event(
            db,
            run.id,
            "approval.changes_requested",
            "Humano solicitou uma iteração versionada de rework AI-native.",
            node_id="Human Approval",
            payload={"comment": comment.strip(), "iteration": prior + 1},
        )
        if commit:
            db.commit()
            db.refresh(run)
            if get_settings().workflow_backend.lower() != "temporal":
                self.resume_ai_native_rework(run.id, run.tenant_id)
        return run
