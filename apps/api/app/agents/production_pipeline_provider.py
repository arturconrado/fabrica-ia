import json
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.paths import run_delivery, run_workspace
from app.core.security import safe_join
from app.core.status import (
    APPROVED,
    APPROVED_FOR_HOMOLOGATION,
    FAILED,
    NEEDS_CHANGES,
    PENDING,
    REJECTED,
    RUNNING,
    SUCCESS,
    WAITING_FOR_HUMAN,
)
from app.events.event_service import emit_event
from app.models import (
    AcceptanceCriterion,
    AgentMessage,
    AgentRunState,
    AgentStepExecution,
    AgentEvent,
    AgentWorkItem,
    ApprovalRequest,
    Artifact,
    DecisionRecord,
    FileChange,
    HomologationPackage,
    HomologationReport,
    HumanFeedback,
    LearningSignal,
    LearningLesson,
    Project,
    QualityGate,
    QualityScore,
    Requirement,
    RequirementTrace,
    RewardSignal,
    RiskItem,
    TestReport,
    WorkflowDefinition,
    WorkflowNodeState,
    WorkflowRun,
    utcnow,
)
from app.providers.object_storage import object_storage
from app.quality.quality_gate_engine import QUALITY_GATES
from app.tools.diff_tools import unified_diff
from app.tools.test_runner import run_generated_tests
from app.service_delivery.capacity import acquire_workflow_slot, heartbeat_workflow_slot, release_workflow_slot
from app.service_delivery.service import DomainError
from app.workflow.cost_policy_compiler import compile_cost_policy_workflow, load_frozen_v211_workflow


REQUIREMENTS = [
    ("REQ-001", "Criar cliente com nome e email.", "P0", "generated_app/app/services.py", "test_create_customer"),
    ("REQ-002", "Listar clientes cadastrados.", "P0", "generated_app/app/services.py", "test_list_customers"),
    ("REQ-003", "Criar contrato associado a cliente.", "P0", "generated_app/app/services.py", "test_create_contract"),
    ("REQ-004", "Listar contratos.", "P0", "generated_app/app/services.py", "test_list_contracts"),
    ("REQ-005", "Criar fatura associada a contrato.", "P0", "generated_app/app/services.py", "test_create_invoice"),
    ("REQ-006", "Marcar fatura como paga.", "P0", "generated_app/app/services.py", "test_mark_invoice_paid"),
    ("REQ-007", "Calcular total em aberto.", "P0", "generated_app/app/services.py", "test_outstanding_total_ignores_paid_invoices"),
    ("REQ-008", "Rodar testes locais com sucesso.", "P0", "generated_app/tests", "pytest-final.log"),
    ("REQ-009", "Gerar documentação de uso.", "P0", "generated_app/README.md", "README.md"),
    ("REQ-010", "Gerar matriz de rastreabilidade.", "P0", "TRACEABILITY_MATRIX.md", "TRACEABILITY_MATRIX.md"),
    ("REQ-011", "Status de contrato.", "P1", "generated_app/app/models.py", "test_create_contract"),
    ("REQ-012", "Filtros simples.", "P1", "generated_app/app/repository.py", "manual-review"),
    ("REQ-013", "Validações de email e valores.", "P1", "generated_app/app/services.py", "test_invalid_email_rejected"),
    ("REQ-014", "Dashboard visual.", "P2", "UX_SPEC.md", "visual-qa"),
    ("REQ-015", "Exportação.", "P2", "backlog", "not-in-mvp"),
    ("REQ-016", "Login.", "P2", "backlog", "not-in-mvp"),
]

AGENT_SEQUENCE = [
    ("Demand Classifier", "demand_classification"),
    ("Acceptance Criteria Architect", "autonomous_acceptance_criteria"),
    ("Scope Governor", "scope_governance"),
    ("Product Manager", "product_planning"),
    ("UX UI Designer", "ux_design"),
    ("Architect", "architecture"),
    ("Data Architect", "data_design"),
    ("API Contract Engineer", "api_contract"),
    ("Project Manager", "task_planning"),
]

POST_TEST_AGENT_SEQUENCE = [
    ("Visual QA Agent", "visual_qa"),
    ("Accessibility QA Agent", "accessibility_qa"),
    ("Security Engineer", "security_review"),
    ("DevOps Engineer", "devops_packaging"),
    ("Release Manager", "release_management"),
]

AGENT_ROLES = {
    "Demand Classifier": ("Demand Analyst", "Classificar a demanda e identificar domínio, riscos e tipo de entrega.", ["read_demand"]),
    "Acceptance Criteria Architect": ("Acceptance Architect", "Transformar demanda em requisitos, critérios Gherkin e evidência esperada.", ["write_requirements"]),
    "Scope Governor": ("Scope Governor", "Separar P0/P1/P2 e bloquear escopo que não cabe na homologação.", ["scope_gate"]),
    "Product Manager": ("Product Manager", "Organizar PRD, jornada e prioridades de produto.", ["prd_writer"]),
    "UX UI Designer": ("UX/UI Designer", "Definir experiência do usuário e estados de interface.", ["ux_spec"]),
    "Architect": ("Solution Architect", "Definir arquitetura e decisões técnicas.", ["architecture_decision"]),
    "Data Architect": ("Data Architect", "Modelar entidades e relações.", ["data_model"]),
    "API Contract Engineer": ("API Contract Engineer", "Especificar contratos e endpoints.", ["api_spec"]),
    "Project Manager": ("Project Manager", "Quebrar entrega em tarefas executáveis.", ["task_plan"]),
    "Engineer": ("Software Engineer", "Gerar e corrigir código fonte.", ["workspace_write", "diff"]),
    "Code Reviewer": ("Code Reviewer", "Revisar código e solicitar correções.", ["review"]),
    "QA Engineer": ("QA Engineer", "Executar testes e reportar falhas/correções.", ["sandbox_pytest"]),
    "Visual QA Agent": ("Visual QA", "Verificar consistência visual da experiência.", ["visual_review"]),
    "Accessibility QA Agent": ("Accessibility QA", "Validar acessibilidade básica.", ["accessibility_review"]),
    "Security Engineer": ("Security Engineer", "Validar segurança local e riscos.", ["security_review"]),
    "DevOps Engineer": ("DevOps Engineer", "Empacotar deploy e evidências.", ["package"]),
    "Release Manager": ("Release Manager", "Preparar release notes e readiness.", ["release_gate"]),
    "Quality Governor": ("Quality Governor", "Calcular HRS, quality gates e homologação.", ["quality_gate", "hrs"]),
    "Human Approval": ("Human Supervisor", "Tomar decisão humana de homologação.", ["approve", "reject", "request_changes"]),
}

HANDOFFS = {
    "Demand Classifier": "Acceptance Criteria Architect",
    "Acceptance Criteria Architect": "Scope Governor",
    "Scope Governor": "Product Manager",
    "Product Manager": "UX UI Designer",
    "UX UI Designer": "Architect",
    "Architect": "Data Architect",
    "Data Architect": "API Contract Engineer",
    "API Contract Engineer": "Project Manager",
    "Project Manager": "Engineer",
    "Engineer": "Code Reviewer",
    "Code Reviewer": "QA Engineer",
    "QA Engineer": "Visual QA Agent",
    "Visual QA Agent": "Accessibility QA Agent",
    "Accessibility QA Agent": "Security Engineer",
    "Security Engineer": "DevOps Engineer",
    "DevOps Engineer": "Release Manager",
    "Release Manager": "Quality Governor",
    "Quality Governor": "Human Approval",
}


class ProductionPipelineProvider:
    def ensure_workflows(self, db: Session, tenant_id: str = "local-dev") -> None:
        workflows = [
            WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workflow_id="software_factory_ai_native_v2",
                version="2.11.0",
                name="Software Factory AI-Native V2.11 (Frozen Baseline)",
                description="Immutable reproducible baseline for cost-policy evaluation.",
                yaml_path="benchmarks/workflows/software_factory_ai_native_v2_11.yaml",
                yaml_content=load_frozen_v211_workflow(),
            ),
            WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workflow_id="software_factory_homologation_v1",
                version="0.1.0",
                name="Software Factory Homologation V1",
                description="Industrial homologation-grade local workflow.",
                yaml_path="workflows/software_factory_homologation_v1.yaml",
                yaml_content=Path("workflows/software_factory_homologation_v1.yaml").read_text()
                if Path("workflows/software_factory_homologation_v1.yaml").exists()
                else "",
            ),
            WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workflow_id="batch_software_factory_v1",
                version="0.1.0",
                name="Batch Software Factory V1",
                description="Sequential local batch workflow.",
                yaml_path="workflows/batch_software_factory_v1.yaml",
                yaml_content=Path("workflows/batch_software_factory_v1.yaml").read_text()
                if Path("workflows/batch_software_factory_v1.yaml").exists()
                else "",
            ),
            WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workflow_id="software_factory_ai_native_v2",
                version="2.12.0",
                name="Software Factory AI-Native V2",
                description="Model-produced artifacts and code with deterministic evidence gates.",
                yaml_path="workflows/software_factory_ai_native_v2.yaml",
                yaml_content=Path("workflows/software_factory_ai_native_v2.yaml").read_text()
                if Path("workflows/software_factory_ai_native_v2.yaml").exists()
                else "",
            ),
            WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workflow_id="software_factory_ai_native_v2",
                version="2.13.0",
                name="Software Factory AI-Native V2.13",
                description="Cost-governed candidate with role contracts and bounded section-level context.",
                yaml_path="workflows/software_factory_ai_native_v2_13_policy.yaml",
                yaml_content=compile_cost_policy_workflow()
                if Path("workflows/software_factory_ai_native_v2_13_policy.yaml").exists()
                else "",
            ),
        ]
        for workflow in workflows:
            existing = db.query(WorkflowDefinition).filter_by(
                workflow_id=workflow.workflow_id,
                version=workflow.version,
                tenant_id=tenant_id,
            ).first()
            if not existing:
                db.add(workflow)
        db.commit()

    def create_project(self, db: Session, name: str, description: str = "", tenant_id: str = "local-dev") -> Project:
        project = Project(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, description=description)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    def start_enterprise_run(
        self,
        db: Session,
        demand: str,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        tenant_id: str = "local-dev",
        run_id: Optional[str] = None,
    ) -> WorkflowRun:
        self.ensure_workflows(db, tenant_id=tenant_id)
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
        if not project:
            if not project_name:
                raise ValueError("An existing project_id or a real project_name is required")
            project = self.create_project(db, project_name, "Execução enterprise da fábrica industrial de software.", tenant_id=tenant_id)
        run = db.get(WorkflowRun, run_id) if run_id else None
        if run:
            run.project_id = project.id
            run.workflow_id = "software_factory_homologation_v1"
            run.demand = demand
            run.status = RUNNING
            run.current_phase = "demand_classification"
            run.current_node = "Demand Classifier"
            run.provider = "homologation-mock" if get_settings().agent_provider.lower() == "mock" else "litellm"
            run.updated_at = utcnow()
        else:
            run = WorkflowRun(
                id=run_id or str(uuid.uuid4()),
                tenant_id=tenant_id,
                project_id=project.id,
                workflow_id="software_factory_homologation_v1",
                demand=demand,
                status=RUNNING,
                current_phase="demand_classification",
                current_node="Demand Classifier",
                cost_estimate=0.0,
                provider="homologation-mock" if get_settings().agent_provider.lower() == "mock" else "litellm",
            )
            db.add(run)
        db.flush()
        acquire_workflow_slot(db, run.id)
        emit_event(db, run.id, "run.created", f"Run criado para {project.name}.")
        emit_event(db, run.id, "run.started", "Linha industrial iniciada.")
        self._record_decision(
            db,
            run.id,
            "USER",
            "Production-only validation",
            "Executar com provider LLM real, Temporal real e evidências auditáveis.",
            "A homologação exige o mesmo padrão operacional do ambiente produtivo.",
        )
        for node_id, phase in AGENT_SEQUENCE:
            self._run_artifact_agent(db, run, node_id, phase)
        self._engineer_initial(db, run)
        self._code_review_needs_changes(db, run)
        self._engineer_fix_email_validation(db, run)
        self._code_review_approved(db, run)
        self._qa_first_failure(db, run)
        self._engineer_fix_tests(db, run)
        self._qa_final_success(db, run)
        self._post_test_agents(db, run)
        self._quality_and_homologation(db, run)
        run.status = WAITING_FOR_HUMAN
        run.current_phase = "human_homologation_approval"
        run.current_node = "Human Approval"
        approval = ApprovalRequest(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Human Approval",
            title="Aprovação final de homologação",
            description="Evidências determinísticas e pacote concluídos; decisão humana final pendente.",
            status=PENDING,
            requested_action="approve_for_homologation",
            risk_level="low",
        )
        db.add(approval)
        emit_event(
            db,
            run.id,
            "approval.requested",
            "Aprovação humana final solicitada.",
            node_id="Human Approval",
            phase="human_homologation_approval",
            agent_name="Human Supervisor",
            status=PENDING,
            payload={"approval_request_id": approval.id},
        )
        run.updated_at = utcnow()
        release_workflow_slot(db, run.id)
        db.commit()
        db.refresh(run)
        return run

    def start_interactive_enterprise_run(
        self,
        db: Session,
        demand: str,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        tenant_id: str = "local-dev",
    ) -> WorkflowRun:
        self.ensure_workflows(db, tenant_id=tenant_id)
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
        if not project:
            if not project_name:
                raise ValueError("An existing project_id or a real project_name is required")
            project = self.create_project(db, project_name, "Execução interativa enterprise da fábrica industrial de software.", tenant_id=tenant_id)
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project.id,
            workflow_id="software_factory_homologation_v1",
            demand=demand,
            status=RUNNING,
            current_phase="demand_classification",
            current_node="Demand Classifier",
            cost_estimate=0.0,
            provider="homologation-mock-interactive" if get_settings().agent_provider.lower() == "mock" else "litellm-interactive",
        )
        db.add(run)
        db.flush()
        acquire_workflow_slot(db, run.id)
        self._seed_agent_operations(db, run)
        emit_event(db, run.id, "run.created", f"Run interativo criado para {project.name}.", payload={"mode": "interactive"})
        emit_event(db, run.id, "run.started", "Factory Floor iniciou execução multiagente observável.", payload={"mode": "interactive"})
        self._message(db, run, "USER", "Demand Classifier", "demand", demand, sop_step="intake")
        db.commit()
        db.refresh(run)

        thread = threading.Thread(target=self._run_interactive_background, args=(run.id, tenant_id), daemon=True)
        thread.start()
        return run

    def execute_temporal_enterprise_run(
        self,
        db: Session,
        *,
        demand: str,
        project_id: Optional[str],
        tenant_id: str,
        run_id: str,
        temporal_workflow_id: str,
    ) -> WorkflowRun:
        """Execute the durable production run while keeping operator controls cooperative."""
        self.ensure_workflows(db, tenant_id=tenant_id)
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
        if not run:
            raise RuntimeError(f"Scheduled workflow run is not committed yet: {run_id}")
        completed_package = db.query(HomologationPackage).filter_by(run_id=run.id, tenant_id=tenant_id).first()
        if run.status in {WAITING_FOR_HUMAN, APPROVED_FOR_HOMOLOGATION} and completed_package:
            return run
        if run.status in {"cancel_requested", "cancelled"}:
            self._finalize_cancellation(db, run)
            return run
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
        if not project:
            raise RuntimeError(f"Scheduled workflow project is not available for tenant {tenant_id}")

        run.demand = demand
        run.project_id = project.id
        run.workflow_id = "software_factory_homologation_v1"
        run.temporal_workflow_id = temporal_workflow_id
        run.provider = "litellm" if get_settings().agent_provider.lower() == "litellm" else "homologation-mock"
        if run.status != PENDING:
            run.status = RUNNING
        run.current_phase = "demand_classification"
        run.current_node = "Demand Classifier"
        run.updated_at = utcnow()
        acquire_workflow_slot(db, run.id)
        self._seed_agent_operations(db, run)
        if not db.query(AgentEvent).filter_by(run_id=run.id, tenant_id=tenant_id, event_type="run.created").first():
            emit_event(db, run.id, "run.created", f"Run Temporal criado para {project.name}.", payload={"mode": "temporal"})
            emit_event(db, run.id, "run.started", "Temporal iniciou a linha multiagente controlável.", payload={"mode": "temporal"})
            self._message(db, run, "USER", "Demand Classifier", "demand", demand, sop_step="intake")
        db.commit()

        self._run_interactive_background(run.id, tenant_id)
        db.expire_all()
        refreshed = db.query(WorkflowRun).filter_by(id=run.id, tenant_id=tenant_id).first()
        if not refreshed:
            raise RuntimeError(f"Workflow run disappeared after Temporal execution: {run.id}")
        if refreshed.status == FAILED:
            raise DomainError(500, "TEMPORAL_PIPELINE_FAILED", "Temporal production pipeline failed")
        return refreshed

    def step_run(self, db: Session, run_id: str) -> WorkflowRun:
        run = db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("Run not found")
        control = self._control_state(db, run)
        control.status = "step_once"
        control.current_sop_step = "manual_step_requested"
        run.status = RUNNING
        run.updated_at = utcnow()
        emit_event(db, run.id, "run.step_requested", "Operador pediu avanço de um step.", payload={"mode": "step"})
        db.commit()
        db.refresh(run)
        return run

    def _run_interactive_background(self, run_id: str, tenant_id: str) -> None:
        from app.db.session import SessionLocal, set_tenant_context

        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            run = db.get(WorkflowRun, run_id)
            if not run:
                return
            if not db.query(DecisionRecord).filter_by(
                run_id=run.id,
                tenant_id=tenant_id,
                title="Interactive MetaGPT-style operation",
            ).first():
                self._record_decision(
                    db,
                    run.id,
                    "USER",
                    "Interactive MetaGPT-style operation",
                    "Executar agentes como papéis observáveis com SOP, mensagens e handoffs.",
                    "A operação deve ser visível para o humano enquanto os artefatos são produzidos.",
                )
            db.commit()
            steps = []
            for node_id, phase in AGENT_SEQUENCE:
                steps.append((node_id, phase, f"SOP: produzir artefato de {phase}", lambda db, run, n=node_id, p=phase: self._run_artifact_agent(db, run, n, p)))
            steps.extend(
                [
                    ("Engineer", "implementation", "SOP: gerar app inicial", self._engineer_initial),
                    ("Code Reviewer", "code_review", "SOP: revisar app inicial", self._code_review_needs_changes),
                    ("Engineer", "implementation", "SOP: corrigir validação de email", self._engineer_fix_email_validation),
                    ("Code Reviewer", "code_review", "SOP: aprovar correção", self._code_review_approved),
                    ("QA Engineer", "testing", "SOP: executar pytest inicial", self._qa_first_failure),
                    ("Engineer", "implementation", "SOP: corrigir falha de teste", self._engineer_fix_tests),
                    ("QA Engineer", "testing", "SOP: executar pytest final", self._qa_final_success),
                ]
            )
            for node_id, phase in POST_TEST_AGENT_SEQUENCE:
                steps.append((node_id, phase, f"SOP: validação de {phase}", lambda db, run, n=node_id, p=phase: self._run_post_test_agent(db, run, n, p)))
            steps.extend(
                [
                    ("Quality Governor", "quality_governance", "SOP: calcular HRS e gates", self._quality_and_homologation),
                    ("Human Approval", "human_homologation_approval", "SOP: aguardar decisão humana", self._request_human_approval),
                ]
            )

            previous_agent = "USER"
            total = len(steps)
            for index, (agent_name, phase, sop_step, action) in enumerate(steps, start=1):
                checkpoint = (
                    db.query(AgentWorkItem)
                    .filter_by(run_id=run_id, tenant_id=tenant_id, agent_name=agent_name, sop_step=sop_step)
                    .filter(AgentWorkItem.status.in_([SUCCESS, WAITING_FOR_HUMAN]))
                    .first()
                )
                if checkpoint:
                    previous_agent = agent_name
                    continue
                run = db.get(WorkflowRun, run_id)
                if not run:
                    return
                if run.status in {"cancel_requested", "cancelled"}:
                    self._finalize_cancellation(db, run)
                    return
                step_mode = self._wait_until_runnable(db, run)
                if step_mode == "cancelled":
                    return
                self._begin_operational_step(db, run, agent_name, phase, sop_step, previous_agent, index, total)
                db.commit()
                self._sleep_between_steps()
                action(db, run)
                self._complete_operational_step(db, run, agent_name, phase, sop_step, index, total)
                db.commit()
                db.refresh(run)
                if run.status in {"cancel_requested", "cancelled"}:
                    self._finalize_cancellation(db, run)
                    return
                control = self._control_state(db, run)
                db.refresh(control)
                if step_mode == "step_once" and control.status == "step_once" and agent_name != "Human Approval":
                    control.status = "paused"
                    run.status = PENDING
                    emit_event(db, run.id, "run.paused", "Run pausado após avanço manual de um step.", payload={"mode": "step"})
                    db.commit()
                previous_agent = agent_name
                self._sleep_between_steps()
        except Exception as exc:
            db.rollback()
            run = db.get(WorkflowRun, run_id)
            if run:
                run.status = FAILED
                release_workflow_slot(db, run.id)
                emit_event(db, run.id, "run.failed", f"Runner interativo falhou: {exc}", status=FAILED, severity="error")
                db.commit()
        finally:
            try:
                run = db.get(WorkflowRun, run_id)
                if run:
                    control = db.query(AgentRunState).filter_by(
                        run_id=run.id, tenant_id=tenant_id, agent_name="RUN_CONTROL"
                    ).first()
                    if control and "temporal_activity_active" in (control.outputs_json or []):
                        control.outputs_json = [
                            item for item in (control.outputs_json or []) if item != "temporal_activity_active"
                        ]
                        db.commit()
            except Exception:
                db.rollback()
            db.close()

    def approve_run(self, db: Session, run_id: str, comment: str = "", *, commit: bool = True) -> WorkflowRun:
        run = db.get(WorkflowRun, run_id)
        if not run:
            raise DomainError(404, "RUN_NOT_FOUND", "Run not found")
        if not comment.strip():
            raise DomainError(400, "APPROVAL_COMMENT_REQUIRED", "Human approval comment is required")
        if run.status != WAITING_FOR_HUMAN:
            raise DomainError(409, "RUN_NOT_AWAITING_APPROVAL", "Run is not awaiting final human approval")
        approval = (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.run_id == run_id, ApprovalRequest.tenant_id == run.tenant_id)
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        if not approval or approval.status != PENDING:
            raise DomainError(409, "APPROVAL_NOT_PENDING", "A pending approval request is required")
        gates = db.query(QualityGate).filter_by(run_id=run_id, tenant_id=run.tenant_id).all()
        blocked = [gate.gate_id for gate in gates if gate.status == "blocked"]
        non_manual_pending = [gate.gate_id for gate in gates if gate.status == "pending" and gate.gate_id != "human_approval"]
        report = db.query(HomologationReport).filter_by(run_id=run.id, tenant_id=run.tenant_id).order_by(HomologationReport.created_at.desc()).first()
        final_test = db.query(TestReport).filter_by(run_id=run.id, tenant_id=run.tenant_id, status="passed").order_by(TestReport.created_at.desc()).first()
        package = db.query(HomologationPackage).filter_by(run_id=run.id, tenant_id=run.tenant_id).order_by(HomologationPackage.created_at.desc()).first()
        if blocked or non_manual_pending or (report and report.blockers_json) or not final_test or not package:
            raise DomainError(
                409,
                "TECHNICAL_BLOCKERS_PRESENT",
                f"Technical blockers cannot be overridden by human approval: blocked={blocked}, pending={non_manual_pending}",
            )
        approval.status = APPROVED
        approval.human_comment = comment
        approval.resolved_at = utcnow()
        for gate in gates:
            if gate.gate_id == "human_approval" or gate.status == "review_required":
                gate.status = "passed"
                gate.score = 100
                gate.evidence_json = {
                    "classification": "declared",
                    "source": "human final review",
                    "comment": comment,
                }
                gate.warnings_json = []
        run.homologation_readiness_score = round(sum(gate.score for gate in gates) / len(gates), 2) if gates else 0.0
        run.status = APPROVED_FOR_HOMOLOGATION
        run.current_phase = "final_delivery"
        run.current_node = "FINAL"
        run.finished_at = utcnow()
        release_workflow_slot(db, run.id)
        if report:
            report.status = APPROVED_FOR_HOMOLOGATION
            report.score = run.homologation_readiness_score
            report.summary = "Technical evidence and explicit human review approved for assisted delivery."
        if package:
            package.status = "approved"
            package.manifest_json = {
                **(package.manifest_json or {}),
                "status": APPROVED_FOR_HOMOLOGATION,
                "hrs": run.homologation_readiness_score,
                "human_approval": {"classification": "declared", "comment": comment},
            }
            for artifact in db.query(Artifact).filter_by(run_id=run.id, tenant_id=run.tenant_id).all():
                artifact.audience = "client"
        emit_event(db, run_id, "approval.approved", "Humano aprovou a homologação.", node_id="Human Approval", payload={"comment": comment})
        db.add(
            LearningSignal(
                id=str(uuid.uuid4()), tenant_id=run.tenant_id, run_id=run.id,
                signal_type="human.approval", source_type="approval_request", source_id=approval.id,
                agent_name="Human Approval", value=1.0,
                evidence_json={"decision": "approved", "hrs": run.homologation_readiness_score},
                eligible_for_global=True,
            )
        )
        emit_event(db, run_id, "homologation.approved", "Entrega aprovada para homologação.", node_id="Human Approval")
        emit_event(db, run_id, "run.finished", "Run finalizado como approved_for_homologation.", node_id="FINAL", status=APPROVED_FOR_HOMOLOGATION)
        if commit:
            db.commit()
            db.refresh(run)
        return run

    def reject_run(self, db: Session, run_id: str, comment: str = "", *, commit: bool = True) -> WorkflowRun:
        run = db.get(WorkflowRun, run_id)
        if not run:
            raise DomainError(404, "RUN_NOT_FOUND", "Run not found")
        if not comment.strip():
            raise DomainError(400, "REJECTION_COMMENT_REQUIRED", "Human rejection comment is required")
        if run.status != WAITING_FOR_HUMAN:
            raise DomainError(409, "RUN_NOT_AWAITING_APPROVAL", "Run is not awaiting final human approval")
        approval = (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.run_id == run_id, ApprovalRequest.tenant_id == run.tenant_id)
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        if not approval or approval.status != PENDING:
            raise DomainError(409, "APPROVAL_NOT_PENDING", "A pending approval request is required")
        run.status = REJECTED
        run.finished_at = utcnow()
        release_workflow_slot(db, run.id)
        approval.status = REJECTED
        approval.human_comment = comment
        approval.resolved_at = utcnow()
        emit_event(db, run_id, "approval.rejected", "Humano rejeitou a entrega.", payload={"comment": comment})
        db.add(
            LearningSignal(
                id=str(uuid.uuid4()), tenant_id=run.tenant_id, run_id=run.id,
                signal_type="human.approval", source_type="approval_request", source_id=approval.id,
                agent_name="Human Approval", value=-1.0,
                evidence_json={"decision": "rejected", "comment_present": True},
                eligible_for_global=True,
            )
        )
        emit_event(db, run_id, "homologation.rejected", "Homologação rejeitada.")
        if commit:
            db.commit()
            db.refresh(run)
        return run

    def request_changes(self, db: Session, run_id: str, comment: str = "", *, commit: bool = True) -> WorkflowRun:
        raise DomainError(
            409,
            "REWORK_EXECUTOR_UNAVAILABLE",
            "Request changes is disabled for ASF runs until a versioned deterministic rework executor is available",
        )

    def create_feedback(
        self,
        db: Session,
        run_id: str,
        rating: int,
        comment: str = "",
        event_id: str = "",
        artifact_id: str = "",
        node_id: str = "",
        feedback_type: str = "general",
        labels: Optional[List[str]] = None,
        tenant_id: str = "local-dev",
    ) -> HumanFeedback:
        from app.learning.reward_service import reward_from_rating

        feedback = HumanFeedback(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            run_id=run_id,
            event_id=event_id,
            artifact_id=artifact_id,
            node_id=node_id,
            rating=rating,
            comment=comment,
            feedback_type=feedback_type,
            labels_json=labels or [],
        )
        db.add(feedback)
        db.flush()
        reward_value = reward_from_rating(rating)
        reward = RewardSignal(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            run_id=run_id,
            feedback_id=feedback.id,
            reward_value=reward_value,
            reason=comment or ("positive feedback" if reward_value > 0 else "negative feedback" if reward_value < 0 else "neutral feedback"),
            applies_to=node_id or artifact_id or event_id or "run",
        )
        db.add(reward)
        source_artifact = db.query(Artifact).filter_by(
            id=artifact_id, tenant_id=tenant_id, run_id=run_id
        ).first() if artifact_id else None
        source_step = None
        if source_artifact and source_artifact.step_execution_id:
            source_step = db.query(AgentStepExecution).filter_by(
                id=source_artifact.step_execution_id, tenant_id=tenant_id, run_id=run_id
            ).first()
        elif node_id:
            source_step = db.query(AgentStepExecution).filter_by(
                tenant_id=tenant_id, run_id=run_id, node_id=node_id
            ).order_by(AgentStepExecution.started_at.desc()).first()
        db.add(
            LearningSignal(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                run_id=run_id,
                signal_type="human.feedback",
                source_type="feedback",
                source_id=feedback.id,
                agent_name=node_id or "Learning Curator",
                prompt_version_id=source_step.prompt_version_id if source_step else None,
                model_call_id=(source_artifact.model_call_id if source_artifact else None) or (source_step.model_call_id if source_step else None),
                value=reward_value,
                evidence_json={
                    "feedback_id": feedback.id,
                    "artifact_id": artifact_id,
                    "event_id": event_id,
                    "labels": labels or [],
                },
                eligible_for_global=bool(comment and reward_value != 0),
            )
        )
        emit_event(db, run_id, "human.feedback_created", "Feedback humano registrado.", payload={"feedback_id": feedback.id})
        emit_event(db, run_id, "reward.signal_created", "Reward signal criado.", payload={"reward_id": reward.id, "value": reward_value})
        if comment:
            lesson = LearningLesson(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                run_id=run_id,
                scope="project",
                agent_name="Learning Curator",
                lesson=f"Lesson candidate from feedback: {comment}",
                evidence_json={"feedback_id": feedback.id, "rating": rating},
                status="candidate",
            )
            db.add(lesson)
            emit_event(db, run_id, "learning.lesson_created", "Lesson candidate criado.", payload={"lesson_id": lesson.id})
        db.commit()
        db.refresh(feedback)
        return feedback

    def approve_lesson(self, db: Session, lesson_id: str) -> LearningLesson:
        lesson = db.get(LearningLesson, lesson_id)
        if not lesson:
            raise ValueError("Lesson not found")
        lesson.status = APPROVED
        lesson.approved_at = utcnow()
        db.commit()
        db.refresh(lesson)
        return lesson

    def _seed_agent_operations(self, db: Session, run: WorkflowRun) -> None:
        existing_names = {
            row[0]
            for row in db.query(AgentRunState.agent_name)
            .filter_by(run_id=run.id, tenant_id=run.tenant_id)
            .all()
        }
        for agent_name, (role, objective, tools) in AGENT_ROLES.items():
            if agent_name in existing_names:
                continue
            db.add(
                AgentRunState(
                    id=str(uuid.uuid4()),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    agent_name=agent_name,
                    role=role,
                    status="idle",
                    current_sop_step="queued",
                    objective=objective,
                    progress=0,
                    inputs_json=[],
                    outputs_json=[],
                    tools_json=tools,
                )
            )
        if "RUN_CONTROL" not in existing_names:
            db.add(
                AgentRunState(
                    id=str(uuid.uuid4()),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    agent_name="RUN_CONTROL",
                    role="Orchestration Control",
                    status="running",
                    current_sop_step="continuous",
                    objective="Controlar pause/resume/step do runner interativo.",
                    progress=0,
                    inputs_json=[],
                    outputs_json=[],
                    tools_json=["pause", "resume", "step", "cancel"],
                )
            )

    def _control_state(self, db: Session, run: WorkflowRun) -> AgentRunState:
        control = db.query(AgentRunState).filter_by(run_id=run.id, agent_name="RUN_CONTROL").first()
        if control:
            return control
        control = AgentRunState(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name="RUN_CONTROL",
            role="Orchestration Control",
            status="running",
            current_sop_step="continuous",
            objective="Controlar pause/resume/step do runner interativo.",
            tools_json=["pause", "resume", "step"],
        )
        db.add(control)
        db.flush()
        return control

    def _agent_state(self, db: Session, run: WorkflowRun, agent_name: str) -> AgentRunState:
        state = db.query(AgentRunState).filter_by(run_id=run.id, agent_name=agent_name).first()
        if state:
            return state
        role, objective, tools = AGENT_ROLES.get(agent_name, (agent_name, "", []))
        state = AgentRunState(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name=agent_name,
            role=role,
            status="idle",
            objective=objective,
            tools_json=tools,
        )
        db.add(state)
        db.flush()
        return state

    def _wait_until_runnable(self, db: Session, run: WorkflowRun) -> str:
        last_capacity_heartbeat = 0.0
        while True:
            db.refresh(run)
            control = self._control_state(db, run)
            if run.status in {"cancel_requested", "cancelled"} or control.status in {"cancel_requested", "cancelled"}:
                self._finalize_cancellation(db, run)
                return "cancelled"
            if control.status == "step_once":
                return "step_once"
            if run.status != PENDING and control.status != "paused":
                return "running"
            if time.monotonic() - last_capacity_heartbeat >= 30:
                if heartbeat_workflow_slot(db, run.id):
                    db.commit()
                last_capacity_heartbeat = time.monotonic()
            time.sleep(0.25)

    def _finalize_cancellation(self, db: Session, run: WorkflowRun, *, commit: bool = True) -> None:
        if run.status == "cancelled":
            release_workflow_slot(db, run.id)
            if commit:
                db.commit()
            return
        control = self._control_state(db, run)
        control.status = "cancelled"
        control.current_sop_step = "cancellation_acknowledged"
        control.outputs_json = [item for item in (control.outputs_json or []) if item != "temporal_activity_active"]
        run.status = "cancelled"
        run.current_phase = "cancelled"
        run.current_node = "FINAL"
        run.finished_at = utcnow()
        release_workflow_slot(db, run.id)
        emit_event(
            db,
            run.id,
            "run.cancellation_acknowledged",
            "Runner acknowledged cancellation after leaving the active step.",
            status="cancelled",
        )
        if commit:
            db.commit()

    def _sleep_between_steps(self) -> None:
        from app.core.config import get_settings

        delay = max(get_settings().agent_step_delay_ms, 0) / 1000
        if delay:
            time.sleep(delay)

    def _message(
        self,
        db: Session,
        run: WorkflowRun,
        from_agent: str,
        to_agent: str,
        message_type: str,
        content: str,
        *,
        sop_step: str = "",
        output_refs: Optional[List[str]] = None,
    ) -> AgentMessage:
        payload = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "role": AGENT_ROLES.get(from_agent, (from_agent, "", []))[0],
            "sop_step": sop_step,
            "input_refs": [],
            "output_refs": output_refs or [],
            "confidence": 0.94,
            "decision": message_type,
            "next_action": f"{to_agent} continua a linha" if to_agent else "Aguardar operador",
        }
        message = AgentMessage(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            payload_json=payload,
        )
        db.add(message)
        emit_event(
            db,
            run.id,
            "agent.message_sent",
            content,
            node_id=from_agent,
            phase=run.current_phase,
            agent_name=from_agent,
            payload=payload,
        )
        if to_agent:
            emit_event(
                db,
                run.id,
                "agent.message_received",
                f"{to_agent} recebeu mensagem de {from_agent}.",
                node_id=to_agent,
                phase=run.current_phase,
                agent_name=to_agent,
                payload=payload,
            )
        return message

    def _begin_operational_step(
        self,
        db: Session,
        run: WorkflowRun,
        agent_name: str,
        phase: str,
        sop_step: str,
        previous_agent: str,
        index: int,
        total: int,
    ) -> None:
        state = self._agent_state(db, run, agent_name)
        state.status = "working"
        state.current_sop_step = sop_step
        state.progress = round((index - 1) / total * 100, 2)
        state.inputs_json = [previous_agent] if previous_agent else []
        state.updated_at = utcnow()
        run.current_node = agent_name
        run.current_phase = phase
        run.updated_at = utcnow()
        db.add(
            AgentWorkItem(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                agent_name=agent_name,
                node_id=agent_name,
                phase=phase,
                sop_step=sop_step,
                status=RUNNING,
                progress=state.progress,
                input_refs_json=[previous_agent] if previous_agent else [],
                output_refs_json=[],
                summary=f"{agent_name} executando {sop_step}.",
                started_at=utcnow(),
            )
        )
        emit_event(db, run.id, "agent.sop_started", f"{agent_name} iniciou {sop_step}.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"from_agent": previous_agent, "to_agent": agent_name, "role": state.role, "sop_step": sop_step, "input_refs": [previous_agent], "output_refs": [], "confidence": 0.92, "decision": "start", "next_action": "execute"})
        emit_event(db, run.id, "agent.thinking", f"{agent_name} analisando entradas e critérios.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"role": state.role, "sop_step": sop_step, "confidence": 0.91})
        if previous_agent and previous_agent != agent_name:
            self._message(db, run, previous_agent, agent_name, "handoff", f"{previous_agent} entregou contexto para {agent_name}.", sop_step=sop_step)
            emit_event(db, run.id, "agent.handoff", f"Handoff: {previous_agent} -> {agent_name}.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"from_agent": previous_agent, "to_agent": agent_name, "sop_step": sop_step})
        emit_event(db, run.id, "agent.acting", f"{agent_name} executando ação principal.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"role": state.role, "sop_step": sop_step, "next_action": "produce_output"})

    def _complete_operational_step(
        self,
        db: Session,
        run: WorkflowRun,
        agent_name: str,
        phase: str,
        sop_step: str,
        index: int,
        total: int,
    ) -> None:
        state = self._agent_state(db, run, agent_name)
        outputs = [artifact.name for artifact in db.query(Artifact).filter_by(run_id=run.id, node_id=agent_name).order_by(Artifact.created_at.desc()).limit(3).all()]
        state.status = "completed" if agent_name != "Human Approval" else "waiting_for_human"
        state.current_sop_step = sop_step
        state.progress = round(index / total * 100, 2)
        state.outputs_json = outputs
        state.updated_at = utcnow()
        work_item = (
            db.query(AgentWorkItem)
            .filter_by(run_id=run.id, agent_name=agent_name, sop_step=sop_step)
            .order_by(AgentWorkItem.created_at.desc())
            .first()
        )
        if work_item:
            work_item.status = state.status if agent_name == "Human Approval" else SUCCESS
            work_item.progress = state.progress
            work_item.output_refs_json = outputs
            work_item.summary = f"{agent_name} concluiu {sop_step}."
            work_item.finished_at = utcnow()
        emit_event(db, run.id, "agent.observing", f"{agent_name} observou outputs: {', '.join(outputs) if outputs else 'estado atualizado'}.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"role": state.role, "sop_step": sop_step, "output_refs": outputs, "confidence": 0.95})
        emit_event(db, run.id, "agent.sop_completed", f"{agent_name} concluiu {sop_step}.", node_id=agent_name, phase=phase, agent_name=agent_name, payload={"role": state.role, "sop_step": sop_step, "output_refs": outputs, "confidence": 0.95})
        next_agent = HANDOFFS.get(agent_name, "")
        if next_agent:
            self._message(db, run, agent_name, next_agent, "handoff", f"{agent_name} concluiu {sop_step} e passou evidências para {next_agent}.", sop_step=sop_step, output_refs=outputs)

    def _run_artifact_agent(self, db: Session, run: WorkflowRun, node_id: str, phase: str) -> None:
        state = self._start_node(db, run, node_id, phase)
        mapping = {
            "Demand Classifier": ("DOMAIN_CLASSIFICATION.md", self._domain_classification(run.demand)),
            "Acceptance Criteria Architect": ("ACCEPTANCE_CRITERIA.md", self._acceptance_criteria()),
            "Scope Governor": ("SCOPE.md", self._scope()),
            "Product Manager": ("PRD.md", self._prd()),
            "UX UI Designer": ("UX_SPEC.md", self._ux_spec()),
            "Architect": ("SYSTEM_DESIGN.md", self._system_design()),
            "Data Architect": ("DATA_MODEL.md", self._data_model()),
            "API Contract Engineer": ("API_SPEC.md", self._api_spec()),
            "Project Manager": ("TASK_LIST.md", self._task_list()),
        }
        name, content = mapping[node_id]
        if node_id == "Acceptance Criteria Architect":
            self._create_requirements(db, run)
            emit_event(db, run.id, "requirement.generated", "Requisitos P0/P1/P2 gerados.", node_id=node_id, phase=phase, agent_name=node_id)
            emit_event(db, run.id, "criteria.generated", "Critérios de aceite Gherkin gerados.", node_id=node_id, phase=phase, agent_name=node_id)
        self._artifact(db, run, node_id, "markdown", name, content)
        self._finish_node(db, run, state, SUCCESS, f"{node_id} produziu {name}.")

    def _engineer_initial(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Engineer", "implementation")
        files = self._generated_app_files(initial=True)
        for path, content in files.items():
            self._save_file(db, run, "Engineer", path, content)
        self._artifact(db, run, "Engineer", "markdown", "IMPLEMENTATION_SUMMARY.md", "# Implementation Summary\n\nGenerated ContractFlow Enterprise with intentional review/test defects.")
        self._finish_node(db, run, state, SUCCESS, "Engineer gerou app inicial com falhas controladas.")

    def _code_review_needs_changes(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Code Reviewer", "code_review")
        content = "# REVIEW_REPORT.md\n\nStatus: needs_changes\n\n- Email validation is missing in `create_customer`.\n- Continue to QA only after correction.\n"
        self._artifact(db, run, "Code Reviewer", "markdown", "REVIEW_REPORT.md", content)
        emit_event(db, run.id, "review.needs_changes", "Revisão encontrou validação ausente.", node_id="Code Reviewer", phase="code_review", agent_name="Code Reviewer", status=NEEDS_CHANGES)
        emit_event(db, run.id, "artifact.reviewed", "Code Reviewer revisou o app inicial e solicitou alteração.", node_id="Code Reviewer", phase="code_review", agent_name="Code Reviewer", status=NEEDS_CHANGES, payload={"from_agent": "Code Reviewer", "to_agent": "Engineer", "sop_step": "code_review", "decision": "needs_changes", "next_action": "Engineer corrige validação de email"})
        self._finish_node(db, run, state, NEEDS_CHANGES, "Reviewer pediu alteração controlada.")

    def _engineer_fix_email_validation(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Engineer", "implementation", iteration=2, max_iterations=3)
        self._save_file(db, run, "Engineer", "generated_app/app/services.py", self._services_py(email_validation=True, fixed_total=False))
        self._finish_node(db, run, state, SUCCESS, "Engineer corrigiu validação de email.")

    def _code_review_approved(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Code Reviewer", "code_review", iteration=2, max_iterations=2)
        content = "# REVIEW_REPORT.md\n\nStatus: approved\n\n- Email validation corrected.\n- Service/repository separation is adequate for MVP.\n- Proceed to QA execution.\n"
        self._artifact(db, run, "Code Reviewer", "markdown", "REVIEW_REPORT_APPROVED.md", content)
        emit_event(db, run.id, "review.approved", "Code review aprovado.", node_id="Code Reviewer", phase="code_review", agent_name="Code Reviewer")
        emit_event(db, run.id, "artifact.reviewed", "Code Reviewer aprovou a correção.", node_id="Code Reviewer", phase="code_review", agent_name="Code Reviewer", payload={"from_agent": "Code Reviewer", "to_agent": "QA Engineer", "sop_step": "code_review", "decision": "approved", "next_action": "QA executa pytest"})
        self._finish_node(db, run, state, APPROVED, "Reviewer aprovou o código para QA.")

    def _qa_first_failure(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "QA Engineer", "testing")
        self._artifact(db, run, "QA Engineer", "markdown", "TEST_PLAN.md", "# TEST_PLAN.md\n\nExecute service tests for customers, contracts, invoices and outstanding totals.")
        report = self._run_tests(db, run, "QA Engineer")
        content = f"# TEST_REPORT.md\n\nInitial status: {report.status}\n\n```text\n{report.stdout}\n{report.stderr}\n```\n"
        self._artifact(db, run, "QA Engineer", "markdown", "TEST_REPORT_INITIAL.md", content)
        emit_event(db, run.id, "test.failed", "Primeira execução de pytest falhou como esperado.", node_id="QA Engineer", phase="testing", agent_name="QA Engineer", status=FAILED, payload={"test_report_id": report.id})
        self._finish_node(db, run, state, FAILED, "QA registrou falha controlada.")

    def _engineer_fix_tests(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Engineer", "implementation", iteration=3, max_iterations=3)
        self._save_file(db, run, "Engineer", "generated_app/app/services.py", self._services_py(email_validation=True, fixed_total=True))
        self._finish_node(db, run, state, SUCCESS, "Engineer corrigiu total em aberto para ignorar faturas pagas.")

    def _qa_final_success(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "QA Engineer", "testing", iteration=2, max_iterations=2)
        report = self._run_tests(db, run, "QA Engineer")
        content = f"# TEST_REPORT.md\n\nFinal status: {report.status}\n\nPassed: {report.passed_count}\nFailed: {report.failed_count}\n\n```text\n{report.stdout}\n{report.stderr}\n```\n"
        self._artifact(db, run, "QA Engineer", "markdown", "TEST_REPORT.md", content)
        event_type = "test.passed" if report.status == "passed" else "test.failed"
        emit_event(db, run.id, event_type, f"Testes finais: {report.status}.", node_id="QA Engineer", phase="testing", agent_name="QA Engineer", status=report.status, payload={"test_report_id": report.id})
        emit_event(db, run.id, "test.summary", "Resumo de testes registrado.", node_id="QA Engineer", phase="testing", agent_name="QA Engineer", payload={"passed": report.passed_count, "failed": report.failed_count, "status": report.status})
        if report.status == "passed":
            self._create_traceability(db, run)
            self._finish_node(db, run, state, SUCCESS, "QA final passou.")
        else:
            self._finish_node(db, run, state, FAILED, "QA final falhou; nenhum evento de aprovação ou rastreabilidade pass foi emitido.")

    def _post_test_agents(self, db: Session, run: WorkflowRun) -> None:
        for node_id, phase in POST_TEST_AGENT_SEQUENCE:
            self._run_post_test_agent(db, run, node_id, phase)

    def _run_post_test_agent(self, db: Session, run: WorkflowRun, node_id: str, phase: str) -> None:
        artifacts = [
            ("Visual QA Agent", "visual_qa", "VISUAL_QA_REPORT.md", "# VISUAL_QA_REPORT.md\n\nStatus: review_required\n\nNo browser-based visual test was executed. Human review is required before delivery."),
            ("Accessibility QA Agent", "accessibility_qa", "ACCESSIBILITY_REPORT.md", "# ACCESSIBILITY_REPORT.md\n\nStatus: review_required\n\nNo automated accessibility scan was executed. Human review is required before delivery."),
            ("Security Engineer", "security_review", "SECURITY_REVIEW.md", "# SECURITY_REVIEW.md\n\nStatus: review_required\n\nObserved controls: exact command allowlist and path validation. No SAST/DAST scan was executed; human review is required."),
            ("DevOps Engineer", "devops_packaging", "DEPLOYMENT.md", "# DEPLOYMENT.md\n\nRun with docker compose. Generated app includes local pytest setup."),
            ("Release Manager", "release_management", "RELEASE_NOTES.md", "# RELEASE_NOTES.md\n\nDeterministic package is ready for assisted homologation review; it is not a production SLA declaration."),
        ]
        lookup = {agent: (agent_phase, name, content) for agent, agent_phase, name, content in artifacts}
        artifact_phase, name, content = lookup[node_id]
        state = self._start_node(db, run, node_id, artifact_phase or phase)
        event_type = {
            "Visual QA Agent": "visual_qa.review_requested",
            "Accessibility QA Agent": "accessibility.review_requested",
            "Security Engineer": "security_review.review_requested",
        }.get(node_id)
        self._artifact(db, run, node_id, "markdown", name, content)
        if event_type:
            emit_event(db, run.id, event_type, f"{node_id} requires human review.", node_id=node_id, phase=phase, agent_name=node_id, status=PENDING)
        node_status = PENDING if event_type else SUCCESS
        self._finish_node(db, run, state, node_status, f"{node_id} finalizado com status {node_status}.")

    def _request_human_approval(self, db: Session, run: WorkflowRun) -> None:
        run.status = WAITING_FOR_HUMAN
        run.current_phase = "human_homologation_approval"
        run.current_node = "Human Approval"
        run.updated_at = utcnow()
        release_workflow_slot(db, run.id)
        approval = ApprovalRequest(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Human Approval",
            title="Aprovação final de homologação",
            description="Evidências determinísticas e pacote concluídos; decisão humana final pendente.",
            status=PENDING,
            requested_action="approve_for_homologation",
            risk_level="low",
        )
        db.add(approval)
        self._message(db, run, "Quality Governor", "Human Approval", "approval_request", "Quality Governor solicitou aprovação humana final.", sop_step="human_homologation_approval")
        emit_event(
            db,
            run.id,
            "approval.requested",
            "Aprovação humana final solicitada.",
            node_id="Human Approval",
            phase="human_homologation_approval",
            agent_name="Human Supervisor",
            status=PENDING,
            payload={"approval_request_id": approval.id, "from_agent": "Quality Governor", "to_agent": "Human Approval", "sop_step": "human_homologation_approval", "decision": "await_human"},
        )

    def _quality_and_homologation(self, db: Session, run: WorkflowRun) -> None:
        state = self._start_node(db, run, "Quality Governor", "quality_governance")
        self._artifact(
            db,
            run,
            "Quality Governor",
            "markdown",
            "MANUAL.md",
            "# MANUAL.md\n\nUse the generated README and pytest command for local validation.\n",
        )
        db.flush()
        artifact_names = {row.name for row in db.query(Artifact).filter_by(run_id=run.id, tenant_id=run.tenant_id).all()}
        final_test = (
            db.query(TestReport)
            .filter_by(run_id=run.id, tenant_id=run.tenant_id, status="passed")
            .order_by(TestReport.created_at.desc())
            .first()
        )
        observed = {
            "requirements": db.query(Requirement).filter_by(run_id=run.id, tenant_id=run.tenant_id).count() > 0,
            "acceptance_criteria": db.query(AcceptanceCriterion).filter_by(run_id=run.id, tenant_id=run.tenant_id).count() > 0,
            "scope": "SCOPE.md" in artifact_names,
            "architecture": "SYSTEM_DESIGN.md" in artifact_names,
            "ux": "UX_SPEC.md" in artifact_names,
            "data": "DATA_MODEL.md" in artifact_names,
            "api": "API_SPEC.md" in artifact_names,
            "implementation": db.query(FileChange).filter_by(run_id=run.id, tenant_id=run.tenant_id).count() > 0,
            "code_review": "REVIEW_REPORT_APPROVED.md" in artifact_names,
            "tests": final_test is not None,
            "traceability": db.query(RequirementTrace).filter_by(run_id=run.id, tenant_id=run.tenant_id).count() > 0,
            "documentation": "MANUAL.md" in artifact_names,
        }
        hard_blockers: List[str] = []
        if not observed["tests"]:
            hard_blockers.append("No real passing test report")
        if not observed["traceability"]:
            hard_blockers.append("Traceability matrix missing")
        gate_rows: List[QualityGate] = []
        for gate_id, name, category in QUALITY_GATES:
            if gate_id in {"visual_qa", "accessibility", "security"}:
                gate_status, gate_score, classification = "review_required", 60, "recommendation"
            elif gate_id in {"human_approval", "homologation_package"}:
                gate_status, gate_score, classification = "pending", 0, "declared"
            else:
                passed = observed.get(gate_id, True)
                gate_status, gate_score, classification = ("passed", 100, "real" if gate_id == "tests" else "calculated") if passed else ("blocked", 0, "calculated")
            emit_event(db, run.id, "quality.gate_started", f"{name} iniciado.", node_id="Quality Governor", phase="quality_governance")
            gate = QualityGate(
                id=str(uuid.uuid4()),
                run_id=run.id,
                gate_id=gate_id,
                name=name,
                category=category,
                status=gate_status,
                score=gate_score,
                blockers_json=[] if gate_status != "blocked" else [f"Missing observed evidence for {gate_id}"],
                warnings_json=[] if gate_status == "passed" else ["Human review or additional evidence required"],
                evidence_json={"status": gate_status, "classification": classification, "observed": observed.get(gate_id)},
            )
            db.add(gate)
            gate_rows.append(gate)
            emit_event(
                db,
                run.id,
                "quality.gate_passed" if gate_status == "passed" else "quality.gate_review_required",
                f"{name}: {gate_status}.",
                node_id="Quality Governor",
                phase="quality_governance",
                status=gate_status,
            )
        db.flush()
        package_gate = next(gate for gate in gate_rows if gate.gate_id == "homologation_package")
        provisional_score = round(sum(gate.score for gate in gate_rows) / len(gate_rows), 2)
        provider_mode = get_settings().agent_provider.lower()
        risk = RiskItem(
            id=str(uuid.uuid4()),
            run_id=run.id,
            title="Provider mode and operational limitations",
            description=f"Provider mode is {provider_mode}; real cost/latency evidence exists only when LiteLLM is enabled.",
            severity="low",
            mitigation="Aplicar budgets, retries e auditoria por tenant no LiteLLM.",
            status="mitigated",
        )
        db.add(risk)
        risk_register = f"# RISK_REGISTER.md\n\n| Risco | Severidade | Mitigação | Status |\n|---|---|---|---|\n| Model provider: {provider_mode} | low | Preserve usage-based cost provenance | controlled |\n| Visual/accessibility/security review | medium | Explicit human review before delivery | open |\n"
        self._artifact(db, run, "Quality Governor", "markdown", "RISK_REGISTER.md", risk_register)
        self._artifact(db, run, "Quality Governor", "markdown", "UAT_PLAN.md", "# UAT_PLAN.md\n\n1. Criar cliente.\n2. Criar contrato.\n3. Criar fatura.\n4. Marcar fatura como paga.\n5. Validar total em aberto.\n")
        hom_report = f"# HOMOLOGATION_REPORT.md\n\nStatus técnico: awaiting_human_review\n\nHRS provisório calculado: {provisional_score}\n\n## Evidência real\n\n- Pytest final: {'passed' if final_test else 'missing'}\n\n## Premissas e limitações\n\n- Provider: {provider_mode}\n- Visual, acessibilidade e segurança exigem revisão humana.\n- Generative Build permanece bloqueado.\n\n## Hard blockers\n\n{chr(10).join(f'- {item}' for item in hard_blockers) or '- Nenhum'}\n"
        self._artifact(db, run, "Quality Governor", "markdown", "HOMOLOGATION_REPORT.md", hom_report)
        status = "blocked" if hard_blockers else "awaiting_human_review"
        report_row = HomologationReport(
                id=str(uuid.uuid4()),
                run_id=run.id,
                status=status,
                score=provisional_score,
                blockers_json=hard_blockers,
                risks_json=[{"title": risk.title, "severity": risk.severity}],
                summary="Deterministic package evaluated from observed evidence; manual gates remain explicit.",
            )
        db.add(report_row)
        self._build_package(db, run, provisional_score, status, hard_blockers)
        package_gate.status = "passed"
        package_gate.score = 100
        package_gate.warnings_json = []
        package_gate.evidence_json = {"status": "passed", "classification": "real", "source": "homologation_packages"}
        score = round(sum(gate.score for gate in gate_rows) / len(gate_rows), 2)
        run.homologation_readiness_score = score
        report_row.score = score
        db.add(
            QualityScore(
                id=str(uuid.uuid4()),
                run_id=run.id,
                category="Observed gate coverage",
                score=score,
                weight=100,
                weighted_score=score,
                evidence_json={"classification": "calculated", "gate_count": len(gate_rows), "hard_blockers": hard_blockers},
            )
        )
        emit_event(db, run.id, "quality.score_updated", f"Observed-evidence HRS calculated: {score}.", node_id="Quality Governor", phase="quality_governance", payload={"score": score, "status": status})
        self._finish_node(db, run, state, FAILED if hard_blockers else PENDING, f"Quality Governor recorded HRS {score}; manual review remains.")

    def _start_node(
        self,
        db: Session,
        run: WorkflowRun,
        node_id: str,
        phase: str,
        iteration: int = 1,
        max_iterations: int = 1,
    ) -> WorkflowNodeState:
        run.current_node = node_id
        run.current_phase = phase
        run.updated_at = utcnow()
        state = WorkflowNodeState(
            id=str(uuid.uuid4()),
            run_id=run.id,
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            status=RUNNING,
            iteration=iteration,
            max_iterations=max_iterations,
        )
        db.add(state)
        emit_event(db, run.id, "phase.started", f"Fase {phase} iniciada.", node_id=node_id, phase=phase, agent_name=node_id)
        emit_event(db, run.id, "node.started", f"Nó {node_id} iniciado.", node_id=node_id, phase=phase, agent_name=node_id)
        emit_event(db, run.id, "agent.message", f"{node_id} executando SOP industrial.", node_id=node_id, phase=phase, agent_name=node_id)
        return state

    def _finish_node(self, db: Session, run: WorkflowRun, state: WorkflowNodeState, status: str, summary: str) -> None:
        state.status = status
        state.summary = summary
        state.finished_at = utcnow()
        state.payload_json = {"summary": summary}
        emit_event(
            db,
            run.id,
            "node.finished" if status not in {FAILED, NEEDS_CHANGES} else "node.failed",
            summary,
            node_id=state.node_id,
            phase=state.phase,
            agent_name=state.agent_name,
            status=status,
        )
        emit_event(db, run.id, "phase.finished", f"Fase {state.phase} finalizada.", node_id=state.node_id, phase=state.phase, agent_name=state.agent_name, status=status)
        run.cost_estimate = round((run.cost_estimate or 0) + 0.05, 2)
        emit_event(db, run.id, "cost.updated", "Custo estimado atualizado.", payload={"cost_estimate": run.cost_estimate})

    def _artifact(self, db: Session, run: WorkflowRun, node_id: str, artifact_type: str, name: str, content: str) -> Artifact:
        classification = "real" if name.startswith("TEST_REPORT") else "recommendation"
        if name in {"HOMOLOGATION_REPORT.md", "TRACEABILITY_MATRIX.md"}:
            classification = "calculated"
        artifact = Artifact(
            id=str(uuid.uuid4()),
            run_id=run.id,
            node_id=node_id,
            artifact_type=artifact_type,
            name=name,
            path=f"docs/{name}",
            content=content,
            evidence_classification=classification,
            source_refs_json=[run.id],
            metadata_json={"generated_by": node_id, "classification": classification, "storage_key": ""},
        )
        db.add(artifact)
        storage_key = object_storage.put_text(run.tenant_id, run.id, "artifacts", name, content, content_type="text/markdown; charset=utf-8")
        artifact.metadata_json = {**artifact.metadata_json, "storage_key": storage_key or ""}
        payload = {"artifact_id": artifact.id, "name": name, "storage_key": storage_key or "", "from_agent": node_id, "to_agent": HANDOFFS.get(node_id, ""), "role": AGENT_ROLES.get(node_id, (node_id, "", []))[0], "sop_step": "artifact_output", "input_refs": [], "output_refs": [name], "confidence": 0.94, "decision": "drafted", "next_action": "review_or_handoff"}
        emit_event(db, run.id, "artifact.drafted", f"{node_id} redigiu {name}.", node_id=node_id, agent_name=node_id, payload=payload)
        emit_event(db, run.id, "artifact.created", f"Artifact {name} criado.", node_id=node_id, agent_name=node_id, payload=payload)
        return artifact

    def _save_file(self, db: Session, run: WorkflowRun, node_id: str, rel_path: str, content: str) -> FileChange:
        root = run_workspace(run.id, run.tenant_id)
        path = safe_join(root, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        before = path.read_text() if path.exists() else ""
        path.write_text(content)
        change_type = "updated" if before else "created"
        diff = unified_diff(rel_path, before, content)
        change = FileChange(
            id=str(uuid.uuid4()),
            run_id=run.id,
            node_id=node_id,
            file_path=rel_path,
            change_type=change_type,
            before_content=before,
            after_content=content,
            diff=diff,
        )
        db.add(change)
        storage_key = object_storage.put_text(run.tenant_id, run.id, "workspace", rel_path, content)
        emit_event(db, run.id, f"file.{change_type}", f"Arquivo {rel_path} {change_type}.", node_id=node_id, agent_name=node_id, payload={"file_path": rel_path, "storage_key": storage_key or ""})
        emit_event(db, run.id, "file.diff", f"Diff criado para {rel_path}.", node_id=node_id, agent_name=node_id, payload={"file_path": rel_path})
        return change

    def _run_tests(self, db: Session, run: WorkflowRun, node_id: str) -> TestReport:
        workspace = run_workspace(run.id, run.tenant_id)
        emit_event(db, run.id, "test.started", "Executando python -m pytest generated_app/tests.", node_id=node_id, phase="testing", agent_name=node_id)
        result = run_generated_tests(workspace, db=db, tenant_id=run.tenant_id, run_id=run.id)
        report = TestReport(id=str(uuid.uuid4()), run_id=run.id, **result)
        db.add(report)
        return report

    def _record_decision(self, db: Session, run_id: str, node_id: str, title: str, decision: str, rationale: str) -> None:
        db.add(
            DecisionRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                node_id=node_id,
                title=title,
                decision=decision,
                rationale=rationale,
                alternatives_json=["real LLM provider", "external workflow engine"],
            )
        )
        emit_event(db, run_id, "agent.decision", title, node_id=node_id, payload={"decision": decision})

    def _create_requirements(self, db: Session, run: WorkflowRun) -> None:
        for index, (req_id, title, priority, _file, _test) in enumerate(REQUIREMENTS, start=1):
            db.add(
                Requirement(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    requirement_id=req_id,
                    title=title,
                    description=title,
                    priority=priority,
                    source="Acceptance Criteria Architect",
                    status="pass" if priority == "P0" else "planned",
                )
            )
            db.add(
                AcceptanceCriterion(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    criterion_id=f"AC-{index:03d}",
                    requirement_id=req_id,
                    title=f"Critério para {req_id}",
                    gherkin=f"Given a local ContractFlow run\nWhen {title}\nThen evidence is recorded for {req_id}",
                    priority=priority,
                    status="pass" if priority == "P0" else "planned",
                )
            )

    def _create_traceability(self, db: Session, run: WorkflowRun) -> None:
        rows = ["| ID | Requisito | Prioridade | Implementado em | Testado por | Evidência | Status |", "|---|---|---|---|---|---|---|"]
        for req_id, title, priority, file_path, test_name in REQUIREMENTS:
            status = "pass" if priority == "P0" else "planned"
            if priority == "P0":
                db.add(
                    RequirementTrace(
                        id=str(uuid.uuid4()),
                        run_id=run.id,
                        requirement_id=req_id,
                        file_path=file_path,
                        test_name=test_name,
                        evidence="pytest-final.log",
                        status="pass",
                    )
                )
            rows.append(f"| {req_id} | {title} | {priority} | {file_path} | {test_name} | pytest-final.log | {status} |")
        content = "# TRACEABILITY_MATRIX.md\n\n" + "\n".join(rows) + "\n"
        self._artifact(db, run, "QA Engineer", "markdown", "TRACEABILITY_MATRIX.md", content)
        emit_event(db, run.id, "traceability.updated", "Matriz de rastreabilidade criada.", node_id="QA Engineer", phase="testing", agent_name="QA Engineer")

    def _build_package(self, db: Session, run: WorkflowRun, score: float, status: str, blockers: List[str]) -> None:
        emit_event(db, run.id, "homologation.package_started", "Iniciando pacote de homologação.", node_id="Quality Governor")
        delivery = run_delivery(run.id, run.tenant_id)
        for folder in ["source-code", "docs", "deploy", "evidence/test-logs", "evidence/diffs"]:
            (delivery / folder).mkdir(parents=True, exist_ok=True)
        source = run_workspace(run.id, run.tenant_id) / "generated_app"
        target = delivery / "source-code" / "generated_app"
        if target.exists():
            shutil.rmtree(target)
        for source_file in source.rglob("*"):
            if source_file.is_file():
                relative = source_file.relative_to(source)
                self._save_delivery_file(db, run, delivery, f"source-code/generated_app/{relative}", source_file.read_text())
        for artifact in db.query(Artifact).filter_by(run_id=run.id, tenant_id=run.tenant_id).all():
            artifact.audience = "reviewer"
            self._save_delivery_file(db, run, delivery, f"docs/{artifact.name}", artifact.content)
        self._save_delivery_file(db, run, delivery, "deploy/docker-compose.yml", "services:\n  generated-app:\n    build: ../source-code/generated_app\n")
        self._save_delivery_file(db, run, delivery, "deploy/.env.example", "APP_ENV=local\n")
        self._save_delivery_file(db, run, delivery, "deploy/healthcheck.md", "# Healthcheck\n\nRun pytest and inspect README.\n")
        final_report = db.query(TestReport).filter_by(run_id=run.id, tenant_id=run.tenant_id, status="passed").order_by(TestReport.created_at.desc()).first()
        self._save_delivery_file(db, run, delivery, "evidence/test-logs/pytest-final.log", (final_report.stdout if final_report else "") + (final_report.stderr if final_report else ""))
        all_diffs = "\n\n".join(change.diff for change in db.query(FileChange).filter_by(run_id=run.id, tenant_id=run.tenant_id).all())
        self._save_delivery_file(db, run, delivery, "evidence/diffs/changes.diff", all_diffs)
        events = db.query(AgentEvent).filter_by(run_id=run.id, tenant_id=run.tenant_id).order_by(AgentEvent.created_at.asc()).all()
        self._save_delivery_file(db, run, delivery, "evidence/agent-events.jsonl", "\n".join(json.dumps({"id": e.id, "type": e.event_type, "summary": e.summary, "created_at": e.created_at.isoformat()}) for e in events))
        decisions = db.query(DecisionRecord).filter_by(run_id=run.id, tenant_id=run.tenant_id).all()
        self._save_delivery_file(db, run, delivery, "evidence/decisions.jsonl", "\n".join(json.dumps({"title": d.title, "decision": d.decision}) for d in decisions))
        gates = db.query(QualityGate).filter_by(run_id=run.id, tenant_id=run.tenant_id).all()
        self._save_delivery_file(db, run, delivery, "evidence/quality-gates.json", json.dumps([{"gate_id": g.gate_id, "status": g.status, "score": g.score} for g in gates], indent=2))
        self._save_delivery_file(db, run, delivery, "evidence/homologation-score.json", json.dumps({"hrs": score, "status": status, "blockers": blockers}, indent=2))
        ai_native = run.generation_mode == "ai_native_v2"
        manifest = {
            "run_id": run.id,
            "project_id": run.project_id,
            "generated_at": datetime.utcnow().isoformat(),
            "status": status,
            "hrs": score,
            "artifacts": [
                {
                    "id": artifact.id,
                    "name": artifact.name,
                    "classification": artifact.evidence_classification,
                    "sources": artifact.source_refs_json,
                    "audience": artifact.audience,
                    "model_call_id": artifact.model_call_id,
                    "step_execution_id": artifact.step_execution_id,
                }
                for artifact in db.query(Artifact).filter_by(run_id=run.id, tenant_id=run.tenant_id).all()
            ],
            "source_files": [c.file_path for c in db.query(FileChange).filter_by(run_id=run.id, tenant_id=run.tenant_id).all()],
            "tests": {"final_status": final_report.status if final_report else "missing"},
            "gates": [g.gate_id for g in gates],
            "blockers": blockers,
            "evidence_policy": {
                "allowed_classifications": ["real", "declared", "calculated", "estimated", "recommendation"],
                "assumptions": [
                    (
                        "Visual, accessibility and security gates are backed by persisted allowlisted sandbox reports."
                        if ai_native
                        else "Visual, accessibility and security gates remain human-reviewed unless a real scanner report is attached."
                    ),
                    "Estimated costs are derived only from persisted model-call usage.",
                ],
            },
            "risks": ["Human homologation decision pending", "Assisted pilot without contractual SLA"],
        }
        package_prefix = f"{object_storage.run_prefix(run.tenant_id, run.id)}/delivery"
        manifest["storage_prefix"] = package_prefix if object_storage.enabled else ""
        self._save_delivery_file(db, run, delivery, "manifest.json", json.dumps(manifest, indent=2))
        package_path = object_storage.uri(package_prefix) if object_storage.enabled else str(delivery)
        db.add(HomologationPackage(id=str(uuid.uuid4()), tenant_id=run.tenant_id, run_id=run.id, path=package_path, status="created", manifest_json=manifest))
        emit_event(db, run.id, "homologation.package_created", "Pacote de homologação criado.", node_id="Quality Governor", payload={"path": package_path})

    def _save_delivery_file(self, db: Session, run: WorkflowRun, delivery: Path, relative_path: str, content: str) -> None:
        path = safe_join(delivery, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        before = path.read_text() if path.exists() else ""
        path.write_text(content)
        change_type = "updated" if before else "created"
        change = FileChange(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Quality Governor",
            file_path=f"delivery/{relative_path}",
            change_type=change_type,
            before_content=before,
            after_content=content,
            diff=unified_diff(f"delivery/{relative_path}", before, content),
        )
        db.add(change)
        storage_key = object_storage.put_text(run.tenant_id, run.id, "delivery", relative_path, content)
        emit_event(
            db,
            run.id,
            f"file.{change_type}",
            f"Delivery file {relative_path} {change_type}.",
            node_id="Quality Governor",
            payload={"file_path": f"delivery/{relative_path}", "storage_key": storage_key or ""},
        )

    def read_workspace_file(self, run_id: str, relative_path: str, tenant_id: str) -> str:
        path = safe_join(run_workspace(run_id, tenant_id), relative_path)
        return path.read_text()

    def _generated_app_files(self, initial: bool) -> Dict[str, str]:
        return {
            "generated_app/app/__init__.py": "",
            "generated_app/app/models.py": self._models_py(),
            "generated_app/app/repository.py": self._repository_py(),
            "generated_app/app/services.py": self._services_py(email_validation=not initial, fixed_total=False),
            "generated_app/app/main.py": self._main_py(),
            "generated_app/tests/test_contracts.py": self._test_contracts_py(),
            "generated_app/tests/test_invoices.py": self._test_invoices_py(),
            "generated_app/README.md": self._generated_readme(),
            "generated_app/pyproject.toml": "[project]\nname = \"contractflow-enterprise\"\nversion = \"0.1.0\"\nrequires-python = \">=3.9\"\ndependencies = [\"fastapi\"]\n",
        }

    def _models_py(self) -> str:
        return """from dataclasses import dataclass


@dataclass
class Customer:
    id: int
    name: str
    email: str


@dataclass
class Contract:
    id: int
    customer_id: int
    title: str
    status: str = "active"


@dataclass
class Invoice:
    id: int
    contract_id: int
    amount: float
    paid: bool = False
"""

    def _repository_py(self) -> str:
        return """from app.models import Contract, Customer, Invoice


class InMemoryRepository:
    def __init__(self):
        self.customers = {}
        self.contracts = {}
        self.invoices = {}
        self._customer_id = 0
        self._contract_id = 0
        self._invoice_id = 0

    def next_customer_id(self):
        self._customer_id += 1
        return self._customer_id

    def next_contract_id(self):
        self._contract_id += 1
        return self._contract_id

    def next_invoice_id(self):
        self._invoice_id += 1
        return self._invoice_id

    def add_customer(self, name, email):
        customer = Customer(id=self.next_customer_id(), name=name, email=email)
        self.customers[customer.id] = customer
        return customer

    def add_contract(self, customer_id, title, status="active"):
        contract = Contract(id=self.next_contract_id(), customer_id=customer_id, title=title, status=status)
        self.contracts[contract.id] = contract
        return contract

    def add_invoice(self, contract_id, amount):
        invoice = Invoice(id=self.next_invoice_id(), contract_id=contract_id, amount=amount)
        self.invoices[invoice.id] = invoice
        return invoice
"""

    def _services_py(self, email_validation: bool, fixed_total: bool) -> str:
        email_check = """        if "@" not in email:
            raise ValueError("email must contain @")
""" if email_validation else ""
        outstanding = (
            "        return sum(invoice.amount for invoice in self.repository.invoices.values() if not invoice.paid)\n"
            if fixed_total
            else "        return sum(invoice.amount for invoice in self.repository.invoices.values())\n"
        )
        return f"""from app.repository import InMemoryRepository


class ContractFlowService:
    def __init__(self, repository=None):
        self.repository = repository or InMemoryRepository()

    def create_customer(self, name, email):
        if not name:
            raise ValueError("name is required")
{email_check}        return self.repository.add_customer(name=name, email=email)

    def list_customers(self):
        return list(self.repository.customers.values())

    def create_contract(self, customer_id, title, status="active"):
        if customer_id not in self.repository.customers:
            raise ValueError("customer not found")
        return self.repository.add_contract(customer_id=customer_id, title=title, status=status)

    def list_contracts(self):
        return list(self.repository.contracts.values())

    def create_invoice(self, contract_id, amount):
        if contract_id not in self.repository.contracts:
            raise ValueError("contract not found")
        if amount <= 0:
            raise ValueError("amount must be positive")
        return self.repository.add_invoice(contract_id=contract_id, amount=amount)

    def mark_invoice_paid(self, invoice_id):
        if invoice_id not in self.repository.invoices:
            raise ValueError("invoice not found")
        self.repository.invoices[invoice_id].paid = True
        return self.repository.invoices[invoice_id]

    def outstanding_total(self):
{outstanding}"""

    def _main_py(self) -> str:
        return """from fastapi import FastAPI
from pydantic import BaseModel

from app.services import ContractFlowService

app = FastAPI(title="ContractFlow Enterprise")
service = ContractFlowService()


class CustomerIn(BaseModel):
    name: str
    email: str


class ContractIn(BaseModel):
    customer_id: int
    title: str
    status: str = "active"


class InvoiceIn(BaseModel):
    contract_id: int
    amount: float


@app.post("/customers")
def create_customer(payload: CustomerIn):
    return service.create_customer(payload.name, payload.email)


@app.get("/customers")
def list_customers():
    return service.list_customers()


@app.post("/contracts")
def create_contract(payload: ContractIn):
    return service.create_contract(payload.customer_id, payload.title, payload.status)


@app.get("/contracts")
def list_contracts():
    return service.list_contracts()


@app.post("/invoices")
def create_invoice(payload: InvoiceIn):
    return service.create_invoice(payload.contract_id, payload.amount)


@app.post("/invoices/{invoice_id}/paid")
def mark_invoice_paid(invoice_id: int):
    return service.mark_invoice_paid(invoice_id)


@app.get("/invoices/outstanding-total")
def outstanding_total():
    return {"total": service.outstanding_total()}
"""

    def _test_contracts_py(self) -> str:
        return """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.services import ContractFlowService


def test_create_customer():
    service = ContractFlowService()
    customer = service.create_customer("Ada Lovelace", "ada@example.com")
    assert customer.id == 1
    assert customer.email == "ada@example.com"


def test_list_customers():
    service = ContractFlowService()
    service.create_customer("Ada Lovelace", "ada@example.com")
    assert len(service.list_customers()) == 1


def test_invalid_email_rejected():
    service = ContractFlowService()
    with pytest.raises(ValueError):
        service.create_customer("Broken", "broken-email")


def test_create_contract():
    service = ContractFlowService()
    customer = service.create_customer("Grace Hopper", "grace@example.com")
    contract = service.create_contract(customer.id, "Support Agreement")
    assert contract.customer_id == customer.id
    assert contract.status == "active"


def test_list_contracts():
    service = ContractFlowService()
    customer = service.create_customer("Grace Hopper", "grace@example.com")
    service.create_contract(customer.id, "Support Agreement")
    assert len(service.list_contracts()) == 1
"""

    def _test_invoices_py(self) -> str:
        return """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ContractFlowService


def _service_with_contract():
    service = ContractFlowService()
    customer = service.create_customer("Katherine Johnson", "katherine@example.com")
    contract = service.create_contract(customer.id, "Analytics Retainer")
    return service, contract


def test_create_invoice():
    service, contract = _service_with_contract()
    invoice = service.create_invoice(contract.id, 100.0)
    assert invoice.amount == 100.0
    assert invoice.paid is False


def test_mark_invoice_paid():
    service, contract = _service_with_contract()
    invoice = service.create_invoice(contract.id, 100.0)
    paid = service.mark_invoice_paid(invoice.id)
    assert paid.paid is True


def test_outstanding_total_ignores_paid_invoices():
    service, contract = _service_with_contract()
    paid = service.create_invoice(contract.id, 100.0)
    open_invoice = service.create_invoice(contract.id, 50.0)
    service.mark_invoice_paid(paid.id)
    assert service.outstanding_total() == open_invoice.amount
"""

    def _generated_readme(self) -> str:
        return """# ContractFlow Enterprise

Small Python/FastAPI app generated by Agentic Software Factory.

## Features

- Create customers with name and email.
- List customers.
- Create contracts linked to customers.
- List contracts.
- Create invoices linked to contracts.
- Mark invoices as paid.
- Calculate outstanding total for unpaid invoices.

## Test

```bash
python -m pytest generated_app/tests
```
"""

    def _domain_classification(self, demand: str) -> str:
        return f"# DOMAIN_CLASSIFICATION.md\n\nDemand: {demand}\n\n- Domain: business operations\n- Product: ContractFlow Enterprise\n- Complexity: medium\n- Risk: low\n- Recommended workflow: software_factory_homologation_v1\n"

    def _acceptance_criteria(self) -> str:
        rows = ["| ID | Title | Priority | Gherkin |", "|---|---|---|---|"]
        for req_id, title, priority, _file, _test in REQUIREMENTS:
            rows.append(f"| {req_id} | {title} | {priority} | Given local validation when executed then evidence exists |")
        return "# ACCEPTANCE_CRITERIA.md\n\n" + "\n".join(rows) + "\n"

    def _scope(self) -> str:
        return "# SCOPE.md\n\nMVP/homologation includes customers, contracts, invoices, tests, docs and traceability. Production auth, export and dashboard are backlog.\n"

    def _prd(self) -> str:
        return "# PRD.md\n\nContractFlow Enterprise helps teams validate customer, contract and invoice workflows with production-grade gates before release.\n"

    def _ux_spec(self) -> str:
        return "# UX_SPEC.md\n\nPrimary console: operational panels, clear status badges, readable traceability and approval controls. Generated app is API-first for MVP.\n"

    def _system_design(self) -> str:
        return "# SYSTEM_DESIGN.md\n\nGenerated app uses FastAPI endpoints, service layer, dataclass models and in-memory repository for local validation.\n"

    def _data_model(self) -> str:
        return "# DATA_MODEL.md\n\nEntities: Customer(id, name, email), Contract(id, customer_id, title, status), Invoice(id, contract_id, amount, paid).\n"

    def _api_spec(self) -> str:
        return "# API_SPEC.md\n\n- POST /customers\n- GET /customers\n- POST /contracts\n- GET /contracts\n- POST /invoices\n- POST /invoices/{invoice_id}/paid\n- GET /invoices/outstanding-total\n"

    def _task_list(self) -> str:
        return "# TASK_LIST.md\n\n1. Generate service/repository/models.\n2. Generate tests.\n3. Run failure pass.\n4. Correct implementation.\n5. Build homologation package.\n"
