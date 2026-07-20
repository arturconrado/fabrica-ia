import hashlib
import json
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.ids import new_id
from app.models import (
    AIActivity,
    AgentRecommendation,
    Artifact,
    Briefing,
    CommercialProposal,
    ComponentInstance,
    Contract,
    Entitlement,
    MvpRun,
    MvpSpec,
    Opportunity,
    LedgerRecord,
    ModelCall,
    Program,
    Project,
    PromptVersion,
    Prospect,
    utcnow,
)
from app.service_delivery.ledger import append_ledger_event
from app.providers.model_gateway import ModelGateway, ModelGatewayError
from app.providers.cost_governor import AIInvocationScope, CostEnvelope, classify_retry
from app.service_delivery.ai_prompts import ACTIVE_PROMPT_VERSION
from app.service_delivery.service import (
    DomainError,
    ServiceDeliveryService,
    actor_event,
    require_entitlement,
    require_limit,
)
from app.services.serialization import model_to_dict, models_to_dict


RAPID_MVP_COMPONENT = "rapid_mvp_factory"


class MvpFactoryService:
    def __init__(self) -> None:
        self.delivery_service = ServiceDeliveryService()
        self.model_gateway = ModelGateway()

    def list_prospects(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return [self._prospect_bundle(db, prospect) for prospect in db.query(Prospect).filter_by(tenant_id=tenant_id).order_by(Prospect.created_at.desc()).all()]

    def create_prospect(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, payload: Dict[str, Any]) -> Prospect:
        entitlement = require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="briefing.intake")
        company = payload.get("company") or payload.get("name") or "New Prospect"
        if company:
            existing = db.query(Prospect).filter_by(tenant_id=tenant_id, company=company).first()
            if existing:
                return existing
        require_limit(entitlement, "prospects", db.query(Prospect).filter_by(tenant_id=tenant_id).count())
        prospect = Prospect(
            id=new_id(),
            tenant_id=tenant_id,
            name=payload.get("name") or company,
            company=company,
            sector=payload.get("sector") or "",
            contact_email=payload.get("contact_email") or "",
            source=payload.get("source") or "manual",
            status="new",
            metadata_json=payload.get("metadata") or {},
        )
        db.add(prospect)
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="prospect",
            resource_id=prospect.id,
            agent_name="Prospecting Copilot",
            activity_type="prospect.created_ai_brief",
            prompt_code="briefing_intake",
            input_json=payload,
            output_json=self._ai_output(
                facts=[f"Prospect registered: {prospect.company or prospect.name}"],
                assumptions=["Commercial fit will be validated after briefing."],
                unknowns=["Budget", "decision maker", "timeline"],
                risks=["Insufficient discovery may reduce proposal accuracy."],
                recommendations=["Collect a concrete business workflow and current pain."],
                confidence=0.74,
            ),
        )
        return prospect

    def create_opportunity(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, payload: Dict[str, Any]) -> Opportunity:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="briefing.intake")
        prospect = db.query(Prospect).filter_by(id=payload.get("prospect_id"), tenant_id=tenant_id).first()
        if not prospect:
            raise DomainError(404, "PROSPECT_NOT_FOUND", "Prospect not found")
        program_id = payload.get("program_id") or None
        project_id = payload.get("project_id") or None
        component_instance_id = payload.get("component_instance_id") or None
        program = db.query(Program).filter_by(id=program_id, tenant_id=tenant_id).first() if program_id else None
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
        component = (
            db.query(ComponentInstance).filter_by(id=component_instance_id, tenant_id=tenant_id).first()
            if component_instance_id
            else None
        )
        if program_id and not program:
            raise DomainError(404, "PROGRAM_NOT_FOUND", "Program not found")
        if project_id and not project:
            raise DomainError(404, "PROJECT_NOT_FOUND", "Project not found")
        if component_instance_id and not component:
            raise DomainError(404, "COMPONENT_INSTANCE_NOT_FOUND", "Component instance not found")
        if project and program and project.program_id != program.id:
            raise DomainError(409, "DELIVERY_REFERENCE_MISMATCH", "Project does not belong to the selected program")
        if component and project and component.project_id != project.id:
            raise DomainError(409, "DELIVERY_REFERENCE_MISMATCH", "Component does not belong to the selected project")
        title = payload.get("title") or f"MVP for {prospect.company or prospect.name}"
        existing = db.query(Opportunity).filter_by(tenant_id=tenant_id, prospect_id=prospect.id, title=title).first()
        if existing:
            return existing
        opportunity = Opportunity(
            id=new_id(),
            tenant_id=tenant_id,
            prospect_id=prospect.id,
            program_id=program_id,
            project_id=project_id,
            component_instance_id=component_instance_id,
            title=title,
            summary=payload.get("summary") or "",
            status="intake",
            stage="briefing",
            value_potential=float(payload.get("value_potential") or 0),
        )
        db.add(opportunity)
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="opportunity",
            resource_id=opportunity.id,
            agent_name="Opportunity Copilot",
            activity_type="opportunity.created_ai_brief",
            prompt_code="idea_validator",
            input_json=payload,
            output_json=self._ai_output(
                facts=[f"Opportunity opened for {prospect.company or prospect.name}"],
                assumptions=["Opportunity is in discovery until briefing is structured."],
                unknowns=["MVP users", "must-have workflow", "data sources"],
                risks=["No structured briefing yet."],
                recommendations=["Run briefing intake before validation."],
                confidence=0.76,
            ),
        )
        return opportunity

    def add_briefing(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, opportunity_id: str, raw_text: str) -> Briefing:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="briefing.intake")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        structured = self._structure_briefing(raw_text)
        briefing = db.query(Briefing).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if not briefing:
            briefing = Briefing(id=new_id(), tenant_id=tenant_id, opportunity_id=opportunity.id, raw_text=raw_text)
            db.add(briefing)
        briefing.raw_text = raw_text
        briefing.structured_json = structured
        briefing.status = "structured"
        briefing.confidence = structured["confidence"]
        briefing.updated_at = utcnow()
        opportunity.summary = structured["summary"]
        if opportunity.status in {"intake", "briefed"}:
            opportunity.status = "briefed"
            opportunity.stage = "validation"
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="opportunity",
            resource_id=opportunity.id,
            agent_name="Briefing Intake Agent",
            activity_type="briefing.structured",
            prompt_code="briefing_intake",
            input_json={"raw_text": raw_text},
            output_json=self._ai_output(
                facts=structured["facts"],
                assumptions=structured["assumptions"],
                unknowns=structured["unknowns"],
                risks=structured["risks"],
                recommendations=structured["recommendations"],
                evidence_refs=[briefing.id],
                confidence=structured["confidence"],
                result={"artifact_markdown": f"# Briefing\n\n{structured['summary']}"},
            ),
        )
        if get_settings().runtime_profile.lower() != "test":
            structured = self._briefing_from_ai(raw_text, activity.output_json)
            briefing.structured_json = structured
            briefing.confidence = structured["confidence"]
            opportunity.summary = structured["summary"]
            db.flush()
        return briefing

    def validate_idea(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, opportunity_id: str) -> Opportunity:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="idea.validate")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        briefing = self._briefing_or_404(db, tenant_id, opportunity.id)
        score = self._validation_score(briefing.structured_json)
        opportunity.validation_score = score["score"]
        opportunity.risk_level = score["risk_level"]
        opportunity.priority = score["priority"]
        if opportunity.status in {"intake", "briefed", "validated"}:
            opportunity.status = "validated"
            opportunity.stage = "scope"
        opportunity.value_potential = score["value_potential"]
        opportunity.updated_at = utcnow()
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="opportunity",
            resource_id=opportunity.id,
            agent_name="Idea Validator Agent",
            activity_type="idea.validated",
            prompt_code="idea_validator",
            input_json=briefing.structured_json,
            output_json=self._ai_output(
                facts=[f"Validation score: {score['score']}"],
                assumptions=briefing.structured_json.get("assumptions", []),
                unknowns=briefing.structured_json.get("unknowns", []),
                risks=score["risks"],
                recommendations=score["recommendations"],
                evidence_refs=[briefing.id],
                confidence=0.84,
            ),
        )
        return opportunity

    def scope_mvp(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, opportunity_id: str) -> MvpSpec:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="mvp.scope")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        briefing = self._briefing_or_404(db, tenant_id, opportunity.id)
        blueprint = self._select_blueprint(briefing.structured_json)
        scope = {
            "mvp": briefing.structured_json.get("mvp_features", []),
            "p1": ["Advanced reporting", "CRM/ERP integration hardening"],
            "p2": ["Public deployment", "Advanced automation"],
            "screens": ["Intake", "Dashboard", "Approval Inbox", "Admin Settings"],
            "apis": ["CRUD core records", "approval command", "dashboard read model"],
        }
        acceptance = [
            {"id": "AC-001", "title": "User can complete the core workflow", "priority": "P0"},
            {"id": "AC-002", "title": "Approvals are recorded in ledger", "priority": "P0"},
            {"id": "AC-003", "title": "Dashboard reflects operational status", "priority": "P0"},
        ]
        spec = db.query(MvpSpec).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if not spec:
            spec = MvpSpec(id=new_id(), tenant_id=tenant_id, opportunity_id=opportunity.id)
            db.add(spec)
        spec.blueprint_ref = blueprint
        spec.stack = "FastAPI + Next.js"
        spec.status = "scoped"
        spec.scope_json = scope
        spec.acceptance_criteria_json = acceptance
        spec.deliverables_json = ["MVP app", "README", "Test evidence", "Homologation package", "Commercial proposal"]
        spec.updated_at = utcnow()
        if opportunity.status in {"intake", "briefed", "validated", "scoped"}:
            opportunity.status = "scoped"
            opportunity.stage = "mvp_generation"
        opportunity.updated_at = utcnow()
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="opportunity",
            resource_id=opportunity.id,
            agent_name="MVP Scoper Agent",
            activity_type="mvp.scoped",
            prompt_code="mvp_scoper",
            input_json=briefing.structured_json,
            output_json=self._ai_output(
                facts=[f"Blueprint selected: {blueprint}", "MVP/P1/P2 split created."],
                assumptions=["FastAPI + Next.js remains the preferred delivery stack."],
                unknowns=briefing.structured_json.get("unknowns", []),
                risks=["Scope creep if P1/P2 items are pulled into MVP."],
                recommendations=["Approve MVP scope before generation."],
                evidence_refs=[spec.id],
                confidence=0.86,
                result={
                    **scope,
                    "acceptance_criteria": acceptance,
                    "deliverables": spec.deliverables_json,
                    "scope_markdown": "# MVP Scope\n\nTest fixture scope.",
                    "acceptance_markdown": "# Acceptance Criteria\n\nTest fixture criteria.",
                },
            ),
        )
        if get_settings().runtime_profile.lower() != "test":
            ai_scope = self._scope_from_ai(activity.output_json)
            spec.blueprint_ref = "ai_native_webapp@1.0"
            spec.stack = "FastAPI + Next.js"
            spec.scope_json = {
                "mvp": ai_scope["mvp"],
                "p1": ai_scope["p1"],
                "p2": ai_scope["p2"],
                "screens": ai_scope["screens"],
                "apis": ai_scope["apis"],
                "knowledge_base_ids": list(briefing.structured_json.get("knowledge_base_ids") or []),
                "source_ai_activity_id": activity.id,
                "scope_markdown": ai_scope["scope_markdown"],
                "acceptance_markdown": ai_scope["acceptance_markdown"],
            }
            spec.acceptance_criteria_json = ai_scope["acceptance_criteria"]
            spec.deliverables_json = ai_scope["deliverables"]
            db.flush()
        return spec

    def generate_mvp(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, opportunity_id: str) -> MvpRun:
        settings = get_settings()
        ai_native = settings.runtime_profile.lower() != "test"
        entitlement = require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="mvp.generate")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        spec = db.query(MvpSpec).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if not spec:
            spec = self.scope_mvp(db, tenant_id, actor_user_id, correlation_id, opportunity.id)
        mvp_run = db.query(MvpRun).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if mvp_run and mvp_run.status in {"ready_for_approval", "approved"}:
            return mvp_run
        if not mvp_run:
            current_mvp_runs = db.query(MvpRun).filter_by(tenant_id=tenant_id).count()
            entitlement = require_entitlement(
                db,
                tenant_id=tenant_id,
                component_code=RAPID_MVP_COMPONENT,
                capability="mvp.generate",
                limit_name="mvp_runs",
                current_value=current_mvp_runs,
            )
            require_limit(entitlement, "mvp_runs", current_mvp_runs)
            mvp_run = MvpRun(id=new_id(), tenant_id=tenant_id, opportunity_id=opportunity.id, mvp_spec_id=spec.id)
            db.add(mvp_run)
            # CommercialProposal references this row by foreign key. The
            # models intentionally do not expose an ORM relationship, so make
            # the parent durable before the dependent proposal is flushed.
            db.flush()
        proposal = self._create_proposal(db, tenant_id, actor_user_id, correlation_id, opportunity, mvp_run, spec)
        builder_activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="mvp_run",
            resource_id=mvp_run.id,
            agent_name="MVP Builder Orchestrator",
            activity_type="mvp.generated",
            prompt_code="mvp_builder_orchestrator",
            input_json={
                "opportunity_id": opportunity.id,
                "title": opportunity.title,
                "approved_scope": spec.scope_json,
                "acceptance_criteria": spec.acceptance_criteria_json,
                "deliverables": spec.deliverables_json,
                "commercial_facts": {
                    "proposal_id": proposal.id,
                    "pricing": proposal.pricing_json,
                },
            },
            output_json=self._ai_output(
                facts=["Test fixture MVP package materialized as Markdown artifacts."],
                assumptions=["Generated app follows selected blueprint."],
                unknowns=["Technical tests and security evidence require an ASF run."],
                risks=["Prospect-specific integrations have not been executed in the test fixture."],
                recommendations=["Review package and proposal before homologation."],
                evidence_refs=[mvp_run.id],
                confidence=0.88,
                result={
                    "orchestration_plan": ["Create ASF run", "Execute gates", "Request human approval"],
                    "artifact_markdown": "# Orchestration Plan\n\nTest fixture plan.",
                },
            ),
        )
        artifacts = (
            self._materialize_ai_mvp_artifacts(db, tenant_id, mvp_run, opportunity, spec, proposal, builder_activity)
            if ai_native
            else self._materialize_mvp_artifacts(db, tenant_id, mvp_run, opportunity, spec, proposal)
        )
        package_gate = "ai_native_prebuild" if ai_native else "deterministic_package"
        gates = [
            {"id": "briefing", "status": "passed", "score": 100, "evidence": ["BRIEFING.md"]},
            {"id": "scope", "status": "passed", "score": 100, "evidence": ["MVP_SCOPE.md", "ACCEPTANCE_CRITERIA.md"]},
            {"id": package_gate, "status": "passed", "score": 100, "evidence": [item.name for item in artifacts]},
            {"id": "tests", "status": "pending", "score": 0, "evidence": []},
            {"id": "security", "status": "pending_human_review", "score": 0, "evidence": ["SECURITY_REVIEW.md"]},
            {"id": "technical_homologation", "status": "pending_asf_run", "score": 0, "evidence": []},
        ]
        mvp_run.status = "ready_for_approval"
        mvp_run.progress = 100.0
        mvp_run.current_phase = "human_approval"
        mvp_run.preview_url = "/mvp-runs/%s" % mvp_run.id
        mvp_run.test_summary_json = {
            "status": "not_run",
            "passed": 0,
            "failed": 0,
            "command": "",
            "reason": "Technical tests require a linked Agentic Software Factory run.",
        }
        mvp_run.quality_gates_json = gates
        mvp_run.package_json = {
            "status": "created",
            "mode": package_gate,
            "artifacts": [
                {"id": item.id, "name": item.name, "classification": item.evidence_classification}
                for item in artifacts
            ],
            "blueprint_ref": spec.blueprint_ref,
            "production_ready_minimum": False,
            "technical_run_required": True,
            "technical_executor_available": ai_native or spec.blueprint_ref == "contractflow_reference@1.0",
        }
        mvp_run.updated_at = utcnow()
        opportunity.status = "mvp_ready"
        opportunity.stage = "proposal"
        opportunity.updated_at = utcnow()
        db.flush()
        return mvp_run

    def decide_mvp_run(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, mvp_run_id: str, decision: str, comment: str) -> MvpRun:
        capability = "mvp.review"
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability=capability)
        mvp_run = self._mvp_run_or_404(db, tenant_id, mvp_run_id)
        if decision == "approve":
            mvp_run.status = "approved"
            mvp_run.approved_at = utcnow()
        elif decision == "reject":
            mvp_run.status = "rejected"
        else:
            mvp_run.status = "changes_requested"
        mvp_run.updated_at = utcnow()
        db.flush()
        self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="mvp_run",
            resource_id=mvp_run.id,
            agent_name="QA Gate Reviewer",
            activity_type=f"mvp.{mvp_run.status}",
            prompt_code="qa_gate_reviewer",
            input_json={"decision": decision, "comment": comment},
            output_json=self._ai_output(
                facts=[f"Human decision recorded: {mvp_run.status}"],
                assumptions=[],
                unknowns=[],
                risks=["Rejected or change-requested MVPs should not be sent to client."],
                recommendations=["Use the decision to update proposal readiness."],
                evidence_refs=[mvp_run.id],
                confidence=0.9,
            ),
        )
        return mvp_run

    def generate_proposal(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        opportunity_id: str,
        idempotency_key: str,
    ) -> CommercialProposal:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="proposal.generate")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        mvp_run = db.query(MvpRun).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if not mvp_run:
            mvp_run = self.generate_mvp(db, tenant_id, actor_user_id, correlation_id, opportunity.id)
        spec = db.query(MvpSpec).filter_by(id=mvp_run.mvp_spec_id, tenant_id=tenant_id).first()
        if not spec:
            raise DomainError(409, "MVP_SCOPE_REQUIRED", "MVP scope must exist before proposal generation")
        proposal = self._create_proposal(db, tenant_id, actor_user_id, correlation_id, opportunity, mvp_run, spec)
        opportunity.stage = "proposal_approval"
        opportunity.updated_at = utcnow()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="opportunity",
            aggregate_id=opportunity.id,
            event_type="opportunity.proposal_generated",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={"summary": "Commercial proposal generated for human approval", "proposal_id": proposal.id},
        )
        return proposal

    def approve_opportunity(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        opportunity_id: str,
        comment: str,
        idempotency_key: str,
    ) -> Opportunity:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="mvp.review")
        if not comment.strip():
            raise DomainError(400, "APPROVAL_REASON_REQUIRED", "A human approval comment is required")
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        mvp_run = db.query(MvpRun).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        proposal = db.query(CommercialProposal).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if not mvp_run or not proposal:
            raise DomainError(409, "MVP_PACKAGE_REQUIRED", "MVP package and proposal are required before approval")
        if mvp_run.status not in {"ready_for_approval", "approved"}:
            raise DomainError(409, "MVP_NOT_APPROVABLE", f"MVP package cannot be approved from status {mvp_run.status}")
        mvp_run.status = "approved"
        mvp_run.approved_at = mvp_run.approved_at or utcnow()
        mvp_run.updated_at = utcnow()
        proposal.status = "approved"
        proposal.updated_at = utcnow()
        opportunity.status = "approved"
        opportunity.stage = "contracting"
        opportunity.updated_at = utcnow()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="opportunity",
            aggregate_id=opportunity.id,
            event_type="opportunity.approved",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={
                "summary": "Human approved the opportunity, AI-native prebuild package and proposal",
                "comment": comment,
                "proposal_id": proposal.id,
                "mvp_run_id": mvp_run.id,
            },
        )
        return opportunity

    def convert_to_delivery(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        opportunity_id: str,
        confirmation: str,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        if confirmation != "activate approved proposal":
            raise DomainError(
                400,
                "CONTRACT_CONFIRMATION_REQUIRED",
                "Explicit confirmation is required to activate the contract and entitlement",
            )
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        proposal = db.query(CommercialProposal).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        mvp_run = db.query(MvpRun).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if opportunity.status != "approved" or not proposal or proposal.status != "approved" or not mvp_run:
            raise DomainError(409, "OPPORTUNITY_APPROVAL_REQUIRED", "Approved opportunity and proposal are required")

        program = db.query(Program).filter_by(id=opportunity.program_id, tenant_id=tenant_id).first() if opportunity.program_id else None
        if not program:
            program = self.delivery_service.create_program(
                db,
                tenant_id,
                actor_user_id,
                correlation_id,
                {"name": f"Delivery - {opportunity.title}", "description": opportunity.summary, "status": "active"},
            )
            opportunity.program_id = program.id
        project = db.query(Project).filter_by(id=opportunity.project_id, tenant_id=tenant_id).first() if opportunity.project_id else None
        if not project:
            project = Project(
                id=new_id(),
                tenant_id=tenant_id,
                program_id=program.id,
                name=opportunity.title,
                description=opportunity.summary,
                scope="AI-native prebuild package followed by a controlled ASF homologation run.",
                owner_user_id=actor_user_id,
                status="active",
            )
            db.add(project)
            db.flush()
            actor_event(
                db,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                aggregate_type="project",
                aggregate_id=project.id,
                event_type="project.created_from_opportunity",
                correlation_id=correlation_id,
                payload={"summary": f"Project created from approved opportunity: {opportunity.title}"},
            )
            opportunity.project_id = project.id

        links = dict(opportunity.metadata_json or {}).get("delivery_links", {})
        contract = db.query(Contract).filter_by(id=links.get("contract_id"), tenant_id=tenant_id).first() if links.get("contract_id") else None
        if not contract:
            contract = self.delivery_service.create_contract(
                db,
                tenant_id,
                actor_user_id,
                correlation_id,
                {
                    "status": "draft",
                    "scope_summary": proposal.content,
                    "commercial_metadata": {"opportunity_id": opportunity.id, "proposal_id": proposal.id, "pricing": proposal.pricing_json},
                },
            )
        contract = self.delivery_service.activate_contract(
            db,
            tenant_id,
            actor_user_id,
            correlation_id,
            contract.id,
            f"{idempotency_key}:contract",
        )
        entitlement = self.delivery_service.add_entitlement(
            db,
            tenant_id,
            actor_user_id,
            correlation_id,
            contract.id,
            {
                "component_code": RAPID_MVP_COMPONENT,
                "status": "granted",
                "limits": {"mvp_runs": 3, "users": 20, "concurrent_workflows": 2},
                "capabilities": [
                    "briefing.intake", "idea.validate", "mvp.scope", "mvp.generate", "mvp.review",
                    "proposal.generate", "package.export", "component.start", "component.view",
                    "asf.run.create", "homologation.package", "delivery.approve",
                ],
                "terms": {
                    "build_mode": "ai_native" if get_settings().runtime_profile.lower() != "test" else "deterministic_package",
                    "generative_build": get_settings().runtime_profile.lower() != "test",
                    "regulated_data": False,
                },
            },
        )
        component = self.delivery_service.create_component_instance(
            db,
            tenant_id,
            actor_user_id,
            correlation_id,
            project.id,
            {"component_code": RAPID_MVP_COMPONENT, "status": "ready", "current_phase": "asf_run_ready"},
        )
        # Bind the delivery instance to the entitlement created from this
        # approved proposal, even when the tenant has older platform grants.
        component.entitlement_id = entitlement.id
        opportunity.component_instance_id = component.id
        opportunity.status = "converted"
        opportunity.stage = "asf_run"
        opportunity.metadata_json = {
            **(opportunity.metadata_json or {}),
            "delivery_links": {
                "contract_id": contract.id,
                "entitlement_id": entitlement.id,
                "program_id": program.id,
                "project_id": project.id,
                "component_instance_id": component.id,
            },
        }
        mvp_run.component_instance_id = component.id
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="opportunity",
            aggregate_id=opportunity.id,
            event_type="opportunity.converted_to_delivery",
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}:converted",
            payload={
                "summary": "Approved opportunity converted to contracted delivery",
                "contract_id": contract.id,
                "entitlement_id": entitlement.id,
                "project_id": project.id,
                "component_instance_id": component.id,
            },
        )
        db.flush()
        return {
            "opportunity": model_to_dict(opportunity),
            "program": model_to_dict(program),
            "project": model_to_dict(project),
            "contract": model_to_dict(contract),
            "entitlement": model_to_dict(entitlement),
            "component_instance": model_to_dict(component),
            "mvp_run": model_to_dict(mvp_run),
        }

    def get_mvp_run(self, db: Session, tenant_id: str, mvp_run_id: str) -> Dict[str, Any]:
        mvp_run = self._mvp_run_or_404(db, tenant_id, mvp_run_id)
        opportunity = db.query(Opportunity).filter_by(id=mvp_run.opportunity_id, tenant_id=tenant_id).first()
        spec = db.query(MvpSpec).filter_by(id=mvp_run.mvp_spec_id, tenant_id=tenant_id).first() if mvp_run.mvp_spec_id else None
        proposal = db.query(CommercialProposal).filter_by(mvp_run_id=mvp_run.id, tenant_id=tenant_id).first()
        activities = db.query(AIActivity).filter_by(tenant_id=tenant_id, resource_id=mvp_run.id).order_by(AIActivity.created_at.desc()).all()
        artifacts = db.query(Artifact).filter_by(tenant_id=tenant_id, mvp_run_id=mvp_run.id).order_by(Artifact.created_at.asc()).all()
        return {
            **model_to_dict(mvp_run),
            "opportunity": model_to_dict(opportunity) if opportunity else None,
            "spec": model_to_dict(spec) if spec else None,
            "proposal": model_to_dict(proposal) if proposal else None,
            "ai_activities": models_to_dict(activities),
            "artifacts": models_to_dict(artifacts),
        }

    def get_mvp_package(self, db: Session, tenant_id: str, mvp_run_id: str) -> Dict[str, Any]:
        mvp_run = self._mvp_run_or_404(db, tenant_id, mvp_run_id)
        artifacts = db.query(Artifact).filter_by(tenant_id=tenant_id, mvp_run_id=mvp_run.id).order_by(Artifact.created_at.asc()).all()
        return {
            "mvp_run_id": mvp_run.id,
            **mvp_run.package_json,
            "artifact_records": models_to_dict(artifacts),
            "test_summary": mvp_run.test_summary_json,
            "quality_gates": mvp_run.quality_gates_json,
        }

    def _materialize_mvp_artifacts(
        self,
        db: Session,
        tenant_id: str,
        mvp_run: MvpRun,
        opportunity: Opportunity,
        spec: MvpSpec,
        proposal: CommercialProposal,
    ) -> List[Artifact]:
        scope = spec.scope_json or {}
        criteria = spec.acceptance_criteria_json or []
        artifact_specs = [
            ("BRIEFING.md", "declared", f"# Briefing\n\n## Problema\n\n{opportunity.summary}\n\n## Premissas\n\nConteúdo fornecido e estruturado durante o intake.\n"),
            ("VALIDATION_REPORT.md", "calculated", f"# Validation Report\n\n- Score calculado: {opportunity.validation_score:.1f}\n- Risco classificado: {opportunity.risk_level}\n- Prioridade: {opportunity.priority}\n\nEste resultado é calculado; não substitui validação humana.\n"),
            ("MVP_SCOPE.md", "declared", f"# MVP Scope\n\n## MVP\n\n{self._markdown_list(scope.get('mvp') or [])}\n\n## P1\n\n{self._markdown_list(scope.get('p1') or [])}\n\n## P2\n\n{self._markdown_list(scope.get('p2') or [])}\n"),
            ("ACCEPTANCE_CRITERIA.md", "declared", f"# Acceptance Criteria\n\n{self._markdown_list(criteria)}\n"),
            ("SOLUTION_BLUEPRINT.md", "recommendation", f"# Solution Blueprint\n\n- Blueprint recomendado: `{spec.blueprint_ref}`\n- Stack recomendada: {spec.stack}\n- Build inicial: deterministic package\n"),
            ("TECHNICAL_ARCHITECTURE.md", "recommendation", "# Technical Architecture\n\nMonólito modular, API FastAPI, UI Next.js, PostgreSQL tenant-scoped, ledger auditável e execução técnica separada por ASF Run.\n"),
            ("DELIVERY_PLAN.md", "estimated", "# Delivery Plan\n\n1. Aprovar package comercial.\n2. Ativar contrato e entitlement.\n3. Criar ASF Run.\n4. Executar testes e gates.\n5. Homologar e entregar.\n"),
            ("QA_PLAN.md", "recommendation", "# QA Plan\n\nOs testes ainda não foram executados. O ASF Run deverá produzir TestReport real, evidências e rastreabilidade antes da homologação técnica.\n"),
            ("SECURITY_REVIEW.md", "recommendation", "# Security Review\n\nStatus: pendente de execução e revisão humana.\n\nValidar tenant isolation, autorização, secrets, dependências, sandbox e dados sensíveis.\n"),
            ("PROPOSAL.md", "declared", f"# Proposal\n\n{proposal.content}\n"),
            ("PRICING_RATIONALE.md", "estimated", f"# Pricing Rationale\n\n{proposal.pricing_json}\n\nValores são estimativas e exigem aprovação comercial humana.\n"),
            ("HOMOLOGATION_CHECKLIST.md", "declared", "# Homologation Checklist\n\n- [x] Briefing registrado\n- [x] Escopo definido\n- [x] Proposta gerada\n- [ ] Contrato e entitlement ativos\n- [ ] ASF Run executado\n- [ ] TestReport aprovado\n- [ ] Security gate aprovado\n- [ ] Aprovação final registrada\n"),
            ("RISK_REGISTER.md", "recommendation", "# Risk Register\n\n- Scope creep: mitigar com gate de escopo.\n- Integrações externas simuladas: validar antes do build técnico.\n- Testes ainda não executados: bloquear homologação técnica.\n"),
            ("LEDGER_TRACE.md", "calculated", f"# Ledger Trace\n\n- Tenant: `{tenant_id}`\n- Opportunity: `{opportunity.id}`\n- MVP Run: `{mvp_run.id}`\n- Proposal: `{proposal.id}`\n\nA trilha completa deve ser consultada no ledger e AI Activity.\n"),
        ]
        records: List[Artifact] = []
        for name, classification, content in artifact_specs:
            artifact = db.query(Artifact).filter_by(tenant_id=tenant_id, mvp_run_id=mvp_run.id, name=name).first()
            if not artifact:
                artifact = Artifact(
                    id=new_id(),
                    tenant_id=tenant_id,
                    run_id=None,
                    mvp_run_id=mvp_run.id,
                    node_id="MVP Builder Orchestrator",
                    artifact_type="markdown",
                    name=name,
                    path=f"mvp/{mvp_run.id}/{name}",
                    content=content,
                    audience="reviewer",
                    evidence_classification=classification,
                    source_refs_json=[opportunity.id, spec.id, proposal.id],
                    metadata_json={"mode": "deterministic_package", "classification": classification},
                )
                db.add(artifact)
            else:
                artifact.content = content
                artifact.audience = "reviewer"
                artifact.evidence_classification = classification
                artifact.source_refs_json = [opportunity.id, spec.id, proposal.id]
            records.append(artifact)
        db.flush()
        return records

    def _materialize_ai_mvp_artifacts(
        self,
        db: Session,
        tenant_id: str,
        mvp_run: MvpRun,
        opportunity: Opportunity,
        spec: MvpSpec,
        proposal: CommercialProposal,
        builder_activity: AIActivity,
    ) -> List[Artifact]:
        """Persist only content produced from real model outputs or deterministic facts.

        This package is commercial/pre-build evidence. Architecture, source code,
        test reports and security evidence are produced later by the ASF run and
        must never be synthesized here.
        """
        briefing = self._briefing_or_404(db, tenant_id, opportunity.id)
        briefing_activity = (
            db.query(AIActivity)
            .filter_by(
                tenant_id=tenant_id,
                resource_type="opportunity",
                resource_id=opportunity.id,
                activity_type="briefing.structured",
            )
            .order_by(AIActivity.created_at.desc())
            .first()
        )
        validation_activity = (
            db.query(AIActivity)
            .filter_by(
                tenant_id=tenant_id,
                resource_type="opportunity",
                resource_id=opportunity.id,
                activity_type="idea.validated",
            )
            .order_by(AIActivity.created_at.desc())
            .first()
        )
        scope_activity = (
            db.query(AIActivity)
            .filter_by(
                tenant_id=tenant_id,
                resource_type="opportunity",
                resource_id=opportunity.id,
                activity_type="mvp.scoped",
            )
            .order_by(AIActivity.created_at.desc())
            .first()
        )
        proposal_activity = (
            db.query(AIActivity)
            .filter_by(
                tenant_id=tenant_id,
                resource_type="commercial_proposal",
                resource_id=proposal.id,
                activity_type="proposal.generated",
            )
            .order_by(AIActivity.created_at.desc())
            .first()
        )
        activities = [briefing_activity, validation_activity, scope_activity, proposal_activity, builder_activity]
        if any(activity is None or not activity.model_call_id for activity in activities):
            raise DomainError(
                409,
                "AI_PROVENANCE_REQUIRED",
                "Every AI-native prebuild artifact requires a persisted real model call",
            )

        structured = briefing.structured_json or {}
        scope = spec.scope_json or {}
        builder_result = builder_activity.output_json.get("result") or {}
        if not isinstance(builder_result.get("artifact_markdown"), str) or not builder_result["artifact_markdown"].strip():
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "MVP Builder did not produce artifact_markdown")

        validation_output = validation_activity.output_json
        validation_notes = self._markdown_list(validation_output.get("facts") or [])
        validation_risks = self._markdown_list(validation_output.get("risks") or [])
        specifications = [
            (
                "BRIEFING.md",
                "declared",
                str(structured.get("artifact_markdown") or "").strip(),
                briefing_activity,
                [briefing.id],
            ),
            (
                "VALIDATION_REPORT.md",
                "calculated",
                "# Validation Report\n\n"
                f"- Score calculado: {float(opportunity.validation_score or 0):.1f}\n"
                f"- Risco classificado: {opportunity.risk_level}\n"
                f"- Prioridade: {opportunity.priority}\n\n"
                f"## Análise do modelo\n\n{validation_notes}\n\n## Riscos\n\n{validation_risks}\n",
                validation_activity,
                [briefing.id],
            ),
            (
                "MVP_SCOPE.md",
                "declared",
                str(scope.get("scope_markdown") or "").strip(),
                scope_activity,
                [spec.id],
            ),
            (
                "ACCEPTANCE_CRITERIA.md",
                "declared",
                str(scope.get("acceptance_markdown") or "").strip(),
                scope_activity,
                [spec.id],
            ),
            (
                "PROPOSAL.md",
                "declared",
                proposal.content.strip(),
                proposal_activity,
                [proposal.id],
            ),
            (
                "PRICING_RATIONALE.md",
                "calculated",
                "# Pricing Rationale\n\n"
                f"- Moeda: {proposal.pricing_json.get('currency')}\n"
                f"- Mínimo: {proposal.pricing_json.get('min')}\n"
                f"- Máximo: {proposal.pricing_json.get('max')}\n"
                f"- Fórmula determinística: `{proposal.pricing_json.get('formula')}`\n\n"
                "O modelo recebeu esses valores como fatos imutáveis; a aprovação comercial permanece humana.\n",
                proposal_activity,
                [proposal.id],
            ),
            (
                "ORCHESTRATION_PLAN.md",
                "recommendation",
                builder_result["artifact_markdown"].strip(),
                builder_activity,
                [mvp_run.id, spec.id, proposal.id],
            ),
        ]
        records: List[Artifact] = []
        for name, classification, content, activity, source_refs in specifications:
            if not content:
                raise DomainError(502, "MODEL_RESPONSE_INVALID", f"AI-native artifact {name} is empty")
            artifact = db.query(Artifact).filter_by(tenant_id=tenant_id, mvp_run_id=mvp_run.id, name=name).first()
            if not artifact:
                artifact = Artifact(
                    id=new_id(),
                    tenant_id=tenant_id,
                    run_id=None,
                    mvp_run_id=mvp_run.id,
                    node_id=activity.agent_name,
                    artifact_type="markdown",
                    name=name,
                    path=f"mvp/{mvp_run.id}/{name}",
                )
                db.add(artifact)
            artifact.content = content
            artifact.audience = "reviewer"
            artifact.evidence_classification = classification
            artifact.source_refs_json = [*source_refs, activity.id, activity.model_call_id]
            artifact.model_call_id = activity.model_call_id
            artifact.metadata_json = {
                "mode": "ai_native_prebuild",
                "classification": classification,
                "ai_activity_id": activity.id,
                "model_call_id": activity.model_call_id,
            }
            records.append(artifact)
        db.flush()
        return records

    def _markdown_list(self, values: List[Any]) -> str:
        if not values:
            return "- Não informado"
        return "\n".join(f"- {value}" for value in values)

    def get_opportunity(self, db: Session, tenant_id: str, opportunity_id: str) -> Dict[str, Any]:
        opportunity = self._opportunity_or_404(db, tenant_id, opportunity_id)
        return self._opportunity_bundle(db, opportunity)

    def list_opportunities(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return [self._opportunity_bundle(db, row) for row in db.query(Opportunity).filter_by(tenant_id=tenant_id).order_by(Opportunity.created_at.desc()).all()]

    def ai_activity(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return models_to_dict(db.query(AIActivity).filter_by(tenant_id=tenant_id).order_by(AIActivity.created_at.desc()).limit(100).all())

    def create_prospect_batch(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        require_entitlement(db, tenant_id=tenant_id, component_code=RAPID_MVP_COMPONENT, capability="briefing.intake")
        prospects = payload.get("prospects") or []
        created = []
        generated_mvp_runs = []
        for index, item in enumerate(prospects[:10], start=1):
            prospect = self.create_prospect(db, tenant_id, actor_user_id, f"{correlation_id}:batch:{index}", item)
            opportunity = self.create_opportunity(
                db,
                tenant_id,
                actor_user_id,
                f"{correlation_id}:batch:{index}",
                {"prospect_id": prospect.id, "title": item.get("opportunity_title") or f"MVP opportunity {index}", "summary": item.get("briefing") or ""},
            )
            if item.get("briefing"):
                self.add_briefing(db, tenant_id, actor_user_id, f"{correlation_id}:batch:{index}", opportunity.id, item["briefing"])
                validated = self.validate_idea(db, tenant_id, actor_user_id, f"{correlation_id}:batch:{index}", opportunity.id)
                if not generated_mvp_runs and validated.validation_score >= 55:
                    self.scope_mvp(db, tenant_id, actor_user_id, f"{correlation_id}:batch:{index}", opportunity.id)
                    run = self.generate_mvp(db, tenant_id, actor_user_id, f"{correlation_id}:batch:{index}", opportunity.id)
                    generated_mvp_runs.append(run.id)
            created.append({"prospect_id": prospect.id, "opportunity_id": opportunity.id})
        return {"created": created, "generated_mvp_runs": generated_mvp_runs, "total": len(created)}

    def _create_proposal(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, opportunity: Opportunity, mvp_run: MvpRun, spec: MvpSpec) -> CommercialProposal:
        proposal = db.query(CommercialProposal).filter_by(tenant_id=tenant_id, opportunity_id=opportunity.id).first()
        if proposal and proposal.status == "approved":
            return proposal
        price_base = max(25000.0, min(120000.0, opportunity.value_potential * 0.12 if opportunity.value_potential else 45000.0))
        content = (
            f"Proposta para {opportunity.title}\n\n"
            "Escopo: MVP demonstravel homologavel com app funcional, testes, pacote de homologacao e demo assistida.\n"
            f"Blueprint: {spec.blueprint_ref}.\n"
            f"Faixa sugerida: R$ {price_base:,.2f} a R$ {price_base * 1.4:,.2f}."
        )
        if not proposal:
            proposal = CommercialProposal(id=new_id(), tenant_id=tenant_id, opportunity_id=opportunity.id, mvp_run_id=mvp_run.id, content=content)
            db.add(proposal)
        proposal.mvp_run_id = mvp_run.id
        proposal.status = "draft"
        proposal.scope_json = spec.scope_json
        proposal.pricing_json = {"currency": "BRL", "min": round(price_base, 2), "max": round(price_base * 1.4, 2), "formula": "mvp_value_band@1.0"}
        proposal.content = content
        proposal.next_steps_json = ["Review MVP package", "Schedule client homologation", "Confirm paid pilot scope"]
        proposal.updated_at = utcnow()
        db.flush()
        activity = self._record_ai_activity(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            resource_type="commercial_proposal",
            resource_id=proposal.id,
            agent_name="Proposal Writer Agent",
            activity_type="proposal.generated",
            prompt_code="proposal_writer",
            input_json={
                "opportunity_id": opportunity.id,
                "mvp_run_id": mvp_run.id,
                "title": opportunity.title,
                "business_problem": opportunity.summary,
                "approved_scope": spec.scope_json,
                "acceptance_criteria": spec.acceptance_criteria_json,
                "deliverables": spec.deliverables_json,
                "deterministic_pricing": proposal.pricing_json,
            },
            output_json=self._ai_output(
                facts=["Commercial proposal generated.", f"Price band formula: {proposal.pricing_json['formula']}"],
                assumptions=["Price band is a first-pass consulting estimate."],
                unknowns=["Final procurement constraints", "payment terms"],
                risks=["Proposal should be reviewed before sending externally."],
                recommendations=["Use verified MVP evidence as the delivery anchor."],
                evidence_refs=[proposal.id, mvp_run.id],
                confidence=0.83,
                result={
                    "title": opportunity.title,
                    "executive_summary": opportunity.summary,
                    "scope": list((spec.scope_json or {}).get("mvp") or []),
                    "deliverables": spec.deliverables_json,
                    "assumptions": ["Test fixture proposal"],
                    "roadmap": ["Homologation"],
                    "next_steps": proposal.next_steps_json,
                    "content_markdown": content,
                },
            ),
        )
        if get_settings().runtime_profile.lower() != "test":
            result = activity.output_json.get("result") or {}
            if not isinstance(result.get("content_markdown"), str) or not result["content_markdown"].strip():
                raise DomainError(502, "MODEL_RESPONSE_INVALID", "Proposal Writer did not produce content_markdown")
            if not isinstance(result.get("next_steps"), list) or not result["next_steps"]:
                raise DomainError(502, "MODEL_RESPONSE_INVALID", "Proposal Writer did not produce next_steps")
            proposal.content = result["content_markdown"].strip()
            proposal.next_steps_json = [str(value) for value in result["next_steps"]]
            proposal.scope_json = {
                **(spec.scope_json or {}),
                "proposal_ai_activity_id": activity.id,
                "proposal_model_call_id": activity.model_call_id,
            }
            db.flush()
        return proposal

    def _record_ai_activity(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        resource_type: str,
        resource_id: str,
        agent_name: str,
        activity_type: str,
        prompt_code: str,
        input_json: Dict[str, Any],
        output_json: Dict[str, Any],
    ) -> AIActivity:
        prompt = db.query(PromptVersion).filter_by(
            code=prompt_code,
            version=ACTIVE_PROMPT_VERSION,
            tenant_id="global",
            status="active",
        ).first()
        if not prompt:
            raise DomainError(
                500,
                "PROMPT_VERSION_NOT_FOUND",
                f"Prompt version not found: {prompt_code}@{ACTIVE_PROMPT_VERSION}",
            )
        idempotency_key = f"{tenant_id}:ai:{resource_type}:{resource_id}:{activity_type}:{correlation_id or 'default'}"
        existing_ledger = db.query(LedgerRecord).filter_by(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
        if existing_ledger:
            existing_activity = db.query(AIActivity).filter_by(tenant_id=tenant_id, ledger_record_id=existing_ledger.id).first()
            if existing_activity:
                return existing_activity

        prompt_tokens = 0
        completion_tokens = 0
        estimated_cost_usd = 0.0
        model_call_id: Optional[str] = None
        activity_status = "test_fixture"
        if get_settings().runtime_profile.lower() != "test":
            settings = get_settings()
            base_messages = [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": json.dumps(input_json, ensure_ascii=False, default=str)},
            ]
            model_result: Dict[str, Any] = {}
            parsed: Any = None
            validation_error = ""
            provider_error = ""
            attempts = max(1, settings.agent_max_step_attempts)
            role_by_prompt = {
                "briefing_intake": "fast",
                "idea_validator": "fast",
                "mvp_scoper": "reasoning",
                "mvp_architect": "reasoning",
                "mvp_builder_orchestrator": "code",
                "qa_gate_reviewer": "reasoning",
                "security_reviewer": "reasoning",
                "proposal_writer": "reasoning",
            }
            output_limit_by_prompt = {
                "briefing_intake": 2500,
                "idea_validator": 2000,
                "mvp_scoper": 5000,
                "mvp_architect": 8000,
                "mvp_builder_orchestrator": 12000,
                "qa_gate_reviewer": 4000,
                "security_reviewer": 4000,
                "proposal_writer": 6000,
            }
            for attempt in range(1, attempts + 1):
                messages = list(base_messages)
                retry_classification = "initial"
                if validation_error or provider_error:
                    retry_classification = classify_retry(validation_error or provider_error)
                    previous_raw = str(((model_result.get("content") or {}).get("raw") or ""))
                    if retry_classification == "schema_repair" and previous_raw:
                        messages = [
                            {
                                "role": "system",
                                "content": "Repair the previous JSON without adding facts. Return only a complete object matching the schema.",
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {"validation_error": validation_error[:2000], "previous_response": previous_raw[:160000]},
                                    ensure_ascii=False,
                                ),
                            },
                        ]
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The previous attempt was rejected. "
                                    f"Reason: {validation_error or provider_error}. Return one complete JSON object "
                                    "that satisfies every required field and type in the supplied response schema."
                                ),
                            }
                        )
                try:
                    configured_role = role_by_prompt.get(prompt_code, "default")
                    selected_role = (
                        "reasoning"
                        if attempt > 1 and configured_role == "fast" and retry_classification == "semantic_escalation"
                        else configured_role
                    )
                    model_result = self.model_gateway.call(
                        db=db,
                        tenant_id=tenant_id,
                        agent_name=agent_name,
                        model_role=selected_role,
                        prompt_version_id=prompt.id,
                        messages=messages,
                        response_schema=prompt.output_schema_json,
                        max_output_tokens=output_limit_by_prompt.get(prompt_code, 4000),
                        routing_policy_version="commercial-2.13.0",
                        invocation_scope=AIInvocationScope(
                            scope_type="opportunity" if resource_type == "opportunity" else "commercial",
                            scope_id=resource_id,
                            correlation_id=correlation_id,
                            policy_version="2.13.0",
                            invocation_id=hashlib.sha256(idempotency_key.encode()).hexdigest(),
                            routing_reason=(
                                "retry_escalation"
                                if selected_role != configured_role
                                else
                                "fast_low_risk_role"
                                if selected_role == "fast"
                                else "protected_quality_role"
                            ),
                            retry_classification=retry_classification,
                            attempt_number=attempt,
                            envelope=CostEnvelope(
                                soft_budget_usd=settings.model_commercial_operation_budget_usd * 0.8,
                                hard_budget_usd=settings.model_commercial_operation_budget_usd,
                            ),
                            metadata={"resource_type": resource_type, "activity_type": activity_type, "prompt_code": prompt_code},
                        ),
                    )
                    provider_error = ""
                except ModelGatewayError as exc:
                    provider_error = str(exc)
                    if classify_retry(exc) == "budget_or_isolation":
                        raise DomainError(409, "AI_OPERATION_BUDGET_BLOCKED", provider_error) from exc
                    if attempt < attempts:
                        continue
                    raise DomainError(
                        502,
                        "MODEL_PROVIDER_FAILED",
                        "The configured model provider did not complete the activity",
                        {"attempts": attempts, "provider_error": provider_error},
                    ) from exc
                parsed = (model_result.get("content") or {}).get("parsed")
                validation_errors = sorted(
                    Draft202012Validator(prompt.output_schema_json).iter_errors(parsed),
                    key=lambda item: tuple(str(part) for part in item.absolute_path),
                )
                validation_error = validation_errors[0].message if validation_errors else ""
                if not validation_error:
                    break
                if attempt == attempts:
                    raise DomainError(
                        502,
                        "MODEL_RESPONSE_INVALID",
                        "The model response did not satisfy the versioned output contract",
                        {"attempts": attempts, "validation_error": validation_error},
                    )
            output_json = parsed
            model_call = db.get(ModelCall, str(model_result["id"]))
            model_call_id = str(model_result["id"])
            if model_call:
                prompt_tokens = model_call.prompt_tokens
                completion_tokens = model_call.completion_tokens
                estimated_cost_usd = model_call.estimated_cost_usd
            activity_status = "completed"
        ledger = append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type=resource_type,
            aggregate_id=resource_id,
            event_type=f"ai.{activity_type}",
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={
                "summary": f"{agent_name}: {activity_type}",
                "agent_name": agent_name,
                "prompt": f"{prompt_code}@{ACTIVE_PROMPT_VERSION}",
                "confidence": output_json.get("confidence", 0),
            },
        )
        existing_activity = db.query(AIActivity).filter_by(tenant_id=tenant_id, ledger_record_id=ledger.id).first()
        if existing_activity:
            return existing_activity
        activity = AIActivity(
            id=new_id(),
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            agent_name=agent_name,
            activity_type=activity_type,
            prompt_code=prompt_code,
            prompt_version=ACTIVE_PROMPT_VERSION,
            status=activity_status,
            input_json=input_json,
            output_json=output_json,
            confidence=float(output_json.get("confidence") or 0.0),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            ledger_record_id=ledger.id,
            model_call_id=model_call_id,
        )
        db.add(activity)
        db.flush()
        recommendations = output_json.get("recommendations") or []
        if recommendations:
            db.add(
                AgentRecommendation(
                    id=new_id(),
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    ai_activity_id=activity.id,
                    title=f"Next step from {agent_name}",
                    recommendation=str(recommendations[0]),
                    severity="info",
                    status="open",
                )
            )
            db.flush()
        return activity

    def _ai_output(
        self,
        *,
        facts: List[str],
        assumptions: List[str],
        unknowns: List[str],
        risks: List[str],
        recommendations: List[str],
        confidence: float,
        evidence_refs: Optional[List[str]] = None,
        requires_human_review: bool = True,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "facts": facts,
            "assumptions": assumptions,
            "unknowns": unknowns,
            "risks": risks,
            "recommendations": recommendations,
            "evidence_refs": evidence_refs or [],
            "confidence": confidence,
            "requires_human_review": requires_human_review,
            "result": result or {},
        }

    def _briefing_from_ai(self, raw_text: str, output: Dict[str, Any]) -> Dict[str, Any]:
        result = output.get("result") or {}
        required_text = ["summary", "artifact_markdown"]
        if any(not isinstance(result.get(field), str) or not result.get(field).strip() for field in required_text):
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "Briefing AI result is missing required text fields")
        for field in ("target_user", "workflow"):
            if not isinstance(result.get(field), (str, list, dict)) or not result.get(field):
                raise DomainError(502, "MODEL_RESPONSE_INVALID", f"Briefing AI result is missing {field}")
        required_lists = ["mvp_features", "integrations", "constraints", "success_metrics"]
        if any(not isinstance(result.get(field), list) for field in required_lists):
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "Briefing AI result is missing required list fields")
        open_questions = result.get("open_questions")
        if open_questions is None:
            open_questions = output.get("unknowns") or []
        if not isinstance(open_questions, list):
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "Briefing AI open questions must be a list")
        lower = raw_text.lower()
        injection = any(term in lower for term in ["ignore regras", "ignore previous", "sem autorização", "bypass"])
        risks = [str(value) for value in output.get("risks") or []]
        if injection and not any("injection" in risk.lower() for risk in risks):
            risks.append("Prompt injection attempt detected by deterministic intake policy.")
        return {
            "summary": result["summary"].strip(),
            "target_user": result["target_user"].strip() if isinstance(result["target_user"], str) else result["target_user"],
            "workflow": result["workflow"].strip() if isinstance(result["workflow"], str) else result["workflow"],
            "mvp_features": [str(value) for value in result["mvp_features"]],
            "integrations": [str(value) for value in result["integrations"]],
            "constraints": [str(value) for value in result["constraints"]],
            "success_metrics": [str(value) for value in result["success_metrics"]],
            "facts": [str(value) for value in output.get("facts") or []],
            "assumptions": [str(value) for value in output.get("assumptions") or []],
            "unknowns": [str(value) for value in open_questions],
            "risks": risks,
            "recommendations": [str(value) for value in output.get("recommendations") or []],
            "confidence": float(output.get("confidence") or 0.0),
            "prompt_injection_detected": injection,
            "artifact_markdown": result["artifact_markdown"],
            "knowledge_base_ids": [],
        }

    def _scope_from_ai(self, output: Dict[str, Any]) -> Dict[str, Any]:
        result = output.get("result") or {}
        for field in ("mvp", "p1", "p2"):
            if not isinstance(result.get(field), (list, dict)):
                raise DomainError(502, "MODEL_RESPONSE_INVALID", f"MVP scope AI result is missing {field}")
        for field in ("screens", "apis"):
            if not isinstance(result.get(field), (list, dict)):
                raise DomainError(502, "MODEL_RESPONSE_INVALID", f"MVP scope AI result is missing {field}")
        list_fields = ["acceptance_criteria", "deliverables"]
        if any(not isinstance(result.get(field), list) for field in list_fields):
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "MVP scope AI result is missing required list fields")
        mvp = self._scope_phase_items(result["mvp"])
        p1 = self._scope_phase_items(result["p1"])
        p2 = self._scope_phase_items(result["p2"])
        if not mvp or not result["acceptance_criteria"]:
            raise DomainError(502, "MODEL_RESPONSE_INVALID", "MVP scope and acceptance criteria cannot be empty")
        for field in ["scope_markdown", "acceptance_markdown"]:
            if not isinstance(result.get(field), str) or not result[field].strip():
                raise DomainError(502, "MODEL_RESPONSE_INVALID", f"MVP scope AI result is missing {field}")
        acceptance = []
        for index, value in enumerate(result["acceptance_criteria"], start=1):
            if isinstance(value, dict):
                acceptance.append(
                    {
                        "id": str(value.get("id") or f"AC-{index:03d}"),
                        "title": str(value.get("title") or value.get("gherkin") or "").strip(),
                        "priority": str(value.get("priority") or "P0"),
                        "gherkin": str(value.get("gherkin") or value.get("title") or "").strip(),
                    }
                )
            else:
                acceptance.append({"id": f"AC-{index:03d}", "title": str(value), "priority": "P0", "gherkin": str(value)})
        return {
            "mvp": mvp,
            "p1": p1,
            "p2": p2,
            "screens": [
                self._scope_item_label(value, kind="screen")
                for value in self._scope_collection_items(result["screens"])
            ],
            "apis": [
                self._scope_item_label(value, kind="api")
                for value in self._scope_collection_items(result["apis"])
            ],
            "acceptance_criteria": acceptance,
            "deliverables": [str(value) for value in result["deliverables"]],
            "scope_markdown": result["scope_markdown"],
            "acceptance_markdown": result["acceptance_markdown"],
        }

    @staticmethod
    def _scope_phase_items(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, dict):
            for key in ("in_scope", "scope", "items", "features"):
                items = value.get(key)
                if isinstance(items, list):
                    return [str(item) for item in items if str(item).strip()]
        return []

    @staticmethod
    def _scope_item_label(value: Any, *, kind: str) -> str:
        if not isinstance(value, dict):
            return str(value)
        purpose = str(value.get("purpose") or "").strip()
        if kind == "api":
            identifier = " ".join(str(value.get(part) or "").strip() for part in ("method", "path")).strip()
        else:
            identifier = str(value.get("name") or "").strip()
        return f"{identifier} — {purpose}" if identifier and purpose else identifier or purpose

    @staticmethod
    def _scope_collection_items(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("mvp", "items", "in_scope", "scope"):
                items = value.get(key)
                if isinstance(items, list):
                    return items
        return []

    def _structure_briefing(self, raw_text: str) -> Dict[str, Any]:
        text = raw_text.strip()
        lower = text.lower()
        injection = any(term in lower for term in ["ignore regras", "ignore previous", "sem autorização", "bypass"])
        is_vague = len(text.split()) < 12 or "algo com ia" in lower
        workflow = "approval workflow" if any(term in lower for term in ["aprovar", "approval", "sla"]) else "enterprise workflow"
        features = ["Core records", "Operational dashboard", "Approval workflow", "Audit trail"]
        unknowns = []
        if is_vague:
            unknowns.extend(["target user", "business workflow", "success metric"])
        if "integra" not in lower:
            unknowns.append("external integrations")
        risks = ["Prompt injection attempt detected."] if injection else []
        if is_vague:
            risks.append("Briefing is too vague for precise scoping.")
        return {
            "summary": text[:240],
            "target_user": "operations team",
            "workflow": workflow,
            "mvp_features": features,
            "facts": [f"Raw briefing received with {len(text.split())} words.", f"Workflow candidate: {workflow}"],
            "assumptions": ["MVP should be homologable locally.", "Tenant isolation and approvals are required."],
            "unknowns": unknowns,
            "risks": risks,
            "recommendations": ["Validate sponsor, data source and approval policy."],
            "confidence": 0.62 if is_vague else 0.82,
            "prompt_injection_detected": injection,
        }

    def _validation_score(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        base = 72.0
        if structured.get("prompt_injection_detected"):
            base -= 25
        if len(structured.get("unknowns") or []) > 2:
            base -= 18
        if "approval" in str(structured.get("workflow", "")).lower():
            base += 10
        score = max(0.0, min(100.0, base))
        risk = "high" if score < 55 else "medium" if score < 75 else "low"
        return {
            "score": round(score, 2),
            "risk_level": risk,
            "priority": "high" if score >= 75 else "medium" if score >= 55 else "low",
            "value_potential": 180000.0 if score >= 75 else 85000.0 if score >= 55 else 30000.0,
            "risks": structured.get("risks") or ["Commercial assumptions need validation."],
            "recommendations": ["Generate MVP scope." if score >= 55 else "Run additional discovery before MVP generation."],
        }

    def _select_blueprint(self, structured: Dict[str, Any]) -> str:
        workflow = str(structured.get("workflow") or "").lower()
        summary = str(structured.get("summary") or "").lower()
        contractflow_terms = [
            ("cliente", "customer"),
            ("contrato", "contract"),
            ("fatura", "invoice"),
        ]
        if all(any(term in summary for term in alternatives) for alternatives in contractflow_terms):
            return "contractflow_reference@1.0"
        if "approval" in workflow:
            return "approval_workflow@1.0"
        if "portal" in workflow:
            return "client_portal@1.0"
        return "enterprise_saas_crud@1.0"

    def _opportunity_or_404(self, db: Session, tenant_id: str, opportunity_id: str) -> Opportunity:
        opportunity = db.query(Opportunity).filter_by(id=opportunity_id, tenant_id=tenant_id).first()
        if not opportunity:
            raise DomainError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found")
        return opportunity

    def _briefing_or_404(self, db: Session, tenant_id: str, opportunity_id: str) -> Briefing:
        briefing = db.query(Briefing).filter_by(opportunity_id=opportunity_id, tenant_id=tenant_id).first()
        if not briefing:
            raise DomainError(409, "BRIEFING_REQUIRED", "Structured briefing is required")
        return briefing

    def _mvp_run_or_404(self, db: Session, tenant_id: str, mvp_run_id: str) -> MvpRun:
        mvp_run = db.query(MvpRun).filter_by(id=mvp_run_id, tenant_id=tenant_id).first()
        if not mvp_run:
            raise DomainError(404, "MVP_RUN_NOT_FOUND", "MVP run not found")
        return mvp_run

    def _prospect_bundle(self, db: Session, prospect: Prospect) -> Dict[str, Any]:
        opportunities = db.query(Opportunity).filter_by(tenant_id=prospect.tenant_id, prospect_id=prospect.id).all()
        return {**model_to_dict(prospect), "opportunities": [self._opportunity_bundle(db, item) for item in opportunities]}

    def _opportunity_bundle(self, db: Session, opportunity: Opportunity) -> Dict[str, Any]:
        prospect = db.query(Prospect).filter_by(id=opportunity.prospect_id, tenant_id=opportunity.tenant_id).first()
        briefing = db.query(Briefing).filter_by(opportunity_id=opportunity.id, tenant_id=opportunity.tenant_id).first()
        spec = db.query(MvpSpec).filter_by(opportunity_id=opportunity.id, tenant_id=opportunity.tenant_id).first()
        mvp_run = db.query(MvpRun).filter_by(opportunity_id=opportunity.id, tenant_id=opportunity.tenant_id).first()
        proposal = db.query(CommercialProposal).filter_by(opportunity_id=opportunity.id, tenant_id=opportunity.tenant_id).first()
        activities = db.query(AIActivity).filter_by(tenant_id=opportunity.tenant_id, resource_type="opportunity", resource_id=opportunity.id).order_by(AIActivity.created_at.desc()).all()
        return {
            **model_to_dict(opportunity),
            "prospect": model_to_dict(prospect) if prospect else None,
            "briefing": model_to_dict(briefing) if briefing else None,
            "mvp_spec": model_to_dict(spec) if spec else None,
            "mvp_run": model_to_dict(mvp_run) if mvp_run else None,
            "proposal": model_to_dict(proposal) if proposal else None,
            "ai_activities": models_to_dict(activities),
        }
