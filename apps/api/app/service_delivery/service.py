from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domain.ids import new_id
from app.models import (
    Approval,
    AuditProjection,
    ComponentDefinition,
    ComponentInstance,
    Contract,
    Entitlement,
    Program,
    Project,
    Score,
    Tenant,
    utcnow,
)
from app.service_delivery.calculations import DeterministicCalculationEngine
from app.service_delivery.ledger import append_ledger_event
from app.services.serialization import model_to_dict, models_to_dict


COMPONENT_DEFINITIONS = [
    {
        "code": "ai_value_discovery",
        "version": "1.0",
        "name": "AI Value Discovery",
        "description": "Onboarding, questionnaires, process opportunities, use cases, ROI and roadmap.",
        "default_blueprint_ref": "discovery_standard@1.0",
        "prerequisites": [],
    },
    {
        "code": "responsible_ai_governance",
        "version": "1.0",
        "name": "Responsible AI & Governance",
        "description": "Inventory, risk classification, controls, policies and governance committee.",
        "default_blueprint_ref": "governance_standard@1.0",
        "prerequisites": ["ai_value_discovery"],
    },
    {
        "code": "ai_enterprise_launchpad",
        "version": "1.0",
        "name": "AI Enterprise Launchpad",
        "description": "Readiness, assistant configuration, pilot, evaluation and scale plan.",
        "default_blueprint_ref": "launchpad_standard@1.0",
        "prerequisites": ["ai_value_discovery", "responsible_ai_governance"],
    },
    {
        "code": "engineering_productivity_accelerator",
        "version": "1.0",
        "name": "AI Engineering Productivity Accelerator",
        "description": "Engineering baseline, repository intelligence, copilots, quality gates and metrics.",
        "default_blueprint_ref": "engineering_productivity@1.0",
        "prerequisites": [],
    },
    {
        "code": "ai_office",
        "version": "1.0",
        "name": "AI Office as a Service",
        "description": "Continuous intake, portfolio, adoption, value, risk and monthly governance.",
        "default_blueprint_ref": "ai_office_monthly@1.0",
        "prerequisites": ["responsible_ai_governance"],
    },
    {
        "code": "rapid_mvp_factory",
        "version": "1.0",
        "name": "Rapid MVP Factory",
        "description": "AI-native prospect intake, idea validation, MVP scoping, generation, QA, package and proposal.",
        "default_blueprint_ref": "rapid_mvp_factory@1.0",
        "prerequisites": [],
    },
]


class DomainError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "details": details or {}})


def ensure_component_definitions(db: Session) -> None:
    for item in COMPONENT_DEFINITIONS:
        existing = db.query(ComponentDefinition).filter_by(code=item["code"], version=item["version"]).first()
        if existing:
            continue
        db.add(
            ComponentDefinition(
                id=new_id(),
                code=item["code"],
                version=item["version"],
                name=item["name"],
                description=item["description"],
                prerequisites_json=item["prerequisites"],
                default_blueprint_ref=item["default_blueprint_ref"],
            )
        )
    db.flush()


def require_entitlement(
    db: Session,
    *,
    tenant_id: str,
    component_code: str,
    capability: str,
    limit_name: str = "",
    current_value: Optional[int] = None,
) -> Entitlement:
    entitlements = (
        db.query(Entitlement)
        .join(Contract, Contract.id == Entitlement.contract_id)
        .filter(Entitlement.tenant_id == tenant_id)
        .filter(Entitlement.component_code == component_code)
        .filter(Entitlement.status == "granted")
        .filter(Contract.status == "active")
        .order_by(Entitlement.created_at.desc())
        .all()
    )
    if not entitlements:
        raise DomainError(
            403,
            "ENTITLEMENT_REQUIRED",
            f"Component capability is not contracted: {component_code}:{capability}",
            {"component_code": component_code, "capability": capability},
        )
    today = date.today().isoformat()
    capability_matches = [row for row in entitlements if capability in (row.capabilities_json or [])]
    if not capability_matches:
        raise DomainError(
            403,
            "CAPABILITY_NOT_GRANTED",
            f"Capability is outside the contracted scope: {capability}",
            {"component_code": component_code, "capability": capability},
        )
    valid_matches = [
        row
        for row in capability_matches
        if (not row.valid_from or row.valid_from <= today) and (not row.valid_until or row.valid_until >= today)
    ]
    if valid_matches:
        if limit_name and current_value is not None:
            capacity_matches = [
                row
                for row in valid_matches
                if not int((row.limits_json or {}).get(limit_name) or 0)
                or current_value < int((row.limits_json or {}).get(limit_name) or 0)
            ]
            if capacity_matches:
                return capacity_matches[0]
            highest_capacity = max(
                valid_matches,
                key=lambda row: int((row.limits_json or {}).get(limit_name) or 0),
            )
            require_limit(highest_capacity, limit_name, current_value)
        return valid_matches[0]
    entitlement = capability_matches[0]
    if entitlement.valid_from and entitlement.valid_from > today:
        raise DomainError(403, "ENTITLEMENT_NOT_YET_VALID", "Entitlement is not valid yet")
    if entitlement.valid_until and entitlement.valid_until < today:
        raise DomainError(403, "ENTITLEMENT_EXPIRED", "Entitlement is expired")
    raise DomainError(403, "ENTITLEMENT_EXPIRED", "Entitlement is expired")


def require_limit(entitlement: Entitlement, limit_name: str, current_value: int) -> None:
    limit = int((entitlement.limits_json or {}).get(limit_name) or 0)
    if limit and current_value >= limit:
        raise DomainError(
            429,
            "ENTITLEMENT_LIMIT_REACHED",
            f"Contracted limit reached: {limit_name}",
            {"component_code": entitlement.component_code, "limit": limit_name, "allowed": limit, "current": current_value},
        )


def actor_event(
    db: Session,
    *,
    tenant_id: str,
    actor_user_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    correlation_id: str,
    idempotency_key: str = "",
    payload: Optional[Dict[str, Any]] = None,
):
    return append_ledger_event(
        db,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload=payload or {},
    )


class ServiceDeliveryService:
    def __init__(self) -> None:
        self.calculation_engine = DeterministicCalculationEngine()

    def dashboard(self, db: Session, tenant_id: str) -> Dict[str, Any]:
        programs = db.query(Program).filter_by(tenant_id=tenant_id).order_by(Program.created_at.desc()).all()
        components = db.query(ComponentInstance).filter_by(tenant_id=tenant_id).all()
        approvals = db.query(Approval).filter_by(tenant_id=tenant_id).order_by(Approval.created_at.desc()).all()
        contracts = db.query(Contract).filter_by(tenant_id=tenant_id).all()
        latest_scores = db.query(Score).filter_by(tenant_id=tenant_id, metric="project_health").order_by(Score.created_at.desc()).all()
        activity = db.query(AuditProjection).filter_by(tenant_id=tenant_id).order_by(AuditProjection.created_at.desc()).limit(10).all()
        return {
            "programs": models_to_dict(programs),
            "components": [self._component_bundle(db, component) for component in components],
            "approvals": models_to_dict(approvals),
            "contracts": models_to_dict(contracts),
            "scores": models_to_dict(latest_scores),
            "activity": models_to_dict(activity),
            "summary": {
                "active_programs": len([row for row in programs if row.status == "active"]),
                "pending_approvals": len([row for row in approvals if row.status == "pending"]),
                "blocked_components": len([row for row in components if row.status == "blocked"]),
                "average_progress": round(sum(row.progress for row in components) / len(components), 2) if components else 0.0,
            },
        }

    def list_programs(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return [self._program_bundle(db, program) for program in db.query(Program).filter_by(tenant_id=tenant_id).all()]

    def get_program(self, db: Session, tenant_id: str, program_id: str) -> Dict[str, Any]:
        program = self._program_or_404(db, tenant_id, program_id)
        return self._program_bundle(db, program)

    def list_program_projects(self, db: Session, tenant_id: str, program_id: str) -> List[Dict[str, Any]]:
        self._program_or_404(db, tenant_id, program_id)
        projects = db.query(Project).filter_by(tenant_id=tenant_id, program_id=program_id).all()
        return [self._project_bundle(db, project) for project in projects]

    def create_program(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, payload: Dict[str, Any]) -> Program:
        program = Program(
            id=new_id(),
            tenant_id=tenant_id,
            name=payload.get("name") or "New AI Program",
            description=payload.get("description") or "",
            sponsor=payload.get("sponsor") or "",
            status=payload.get("status") or "active",
            start_date=payload.get("start_date") or "",
            target_end_date=payload.get("target_end_date") or "",
        )
        db.add(program)
        db.flush()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="program",
            aggregate_id=program.id,
            event_type="program.created",
            correlation_id=correlation_id,
            payload={"summary": f"Program created: {program.name}"},
        )
        return program

    def create_contract(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, payload: Dict[str, Any]) -> Contract:
        contract = Contract(
            id=new_id(),
            tenant_id=tenant_id,
            contract_number=payload.get("contract_number") or f"CON-{new_id()[:8]}",
            status=payload.get("status") or "draft",
            valid_from=payload.get("valid_from") or "",
            valid_until=payload.get("valid_until") or "",
            commercial_metadata_json=payload.get("commercial_metadata") or {},
            scope_summary=payload.get("scope_summary") or "",
        )
        db.add(contract)
        db.flush()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="contract",
            aggregate_id=contract.id,
            event_type="contract.created",
            correlation_id=correlation_id,
            payload={"summary": f"Contract created: {contract.contract_number}"},
        )
        return contract

    def activate_contract(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, contract_id: str, idempotency_key: str) -> Contract:
        contract = self._contract_or_404(db, tenant_id, contract_id)
        if contract.status == "active":
            return contract
        contract.status = "active"
        contract.updated_at = utcnow()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="contract",
            aggregate_id=contract.id,
            event_type="contract.activated",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={"summary": f"Contract activated: {contract.contract_number}"},
        )
        return contract

    def add_entitlement(self, db: Session, tenant_id: str, actor_user_id: str, correlation_id: str, contract_id: str, payload: Dict[str, Any]) -> Entitlement:
        ensure_component_definitions(db)
        contract = self._contract_or_404(db, tenant_id, contract_id)
        component_code = payload.get("component_code")
        definition = db.query(ComponentDefinition).filter_by(code=component_code, version=payload.get("component_version") or "1.0").first()
        if not definition:
            raise DomainError(404, "COMPONENT_DEFINITION_NOT_FOUND", "Component definition not found")
        existing = db.query(Entitlement).filter_by(tenant_id=tenant_id, contract_id=contract.id, component_code=component_code).first()
        if existing:
            return existing
        entitlement = Entitlement(
            id=new_id(),
            tenant_id=tenant_id,
            contract_id=contract.id,
            component_definition_id=definition.id,
            component_code=component_code,
            status=payload.get("status") or "granted",
            valid_from=payload.get("valid_from") or contract.valid_from,
            valid_until=payload.get("valid_until") or contract.valid_until,
            limits_json=payload.get("limits") or {},
            capabilities_json=payload.get("capabilities") or [],
            terms_json=payload.get("terms") or {},
        )
        db.add(entitlement)
        db.flush()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="entitlement",
            aggregate_id=entitlement.id,
            event_type="entitlement.created",
            correlation_id=correlation_id,
            payload={"summary": f"Entitlement created: {component_code}", "component_code": component_code},
        )
        return entitlement

    def set_entitlement_status(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        entitlement_id: str,
        status: str,
        idempotency_key: str,
    ) -> Entitlement:
        entitlement = db.query(Entitlement).filter_by(id=entitlement_id, tenant_id=tenant_id).first()
        if not entitlement:
            raise DomainError(404, "ENTITLEMENT_NOT_FOUND", "Entitlement not found")
        if entitlement.status == status:
            return entitlement
        entitlement.status = status
        entitlement.updated_at = utcnow()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="entitlement",
            aggregate_id=entitlement.id,
            event_type=f"entitlement.{status}",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={"summary": f"Entitlement status changed to {status}", "component_code": entitlement.component_code},
        )
        return entitlement

    def create_component_instance(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        project_id: str,
        payload: Dict[str, Any],
    ) -> ComponentInstance:
        ensure_component_definitions(db)
        project = self._project_or_404(db, tenant_id, project_id)
        component_code = payload.get("component_code")
        entitlement = require_entitlement(
            db,
            tenant_id=tenant_id,
            component_code=component_code,
            capability="component.start",
        )
        definition = db.query(ComponentDefinition).filter_by(id=entitlement.component_definition_id).first()
        if not definition:
            raise DomainError(404, "COMPONENT_DEFINITION_NOT_FOUND", "Component definition not found")
        existing = db.query(ComponentInstance).filter_by(tenant_id=tenant_id, project_id=project.id, component_code=component_code).first()
        if existing:
            return existing
        instance = ComponentInstance(
            id=new_id(),
            tenant_id=tenant_id,
            project_id=project.id,
            component_definition_id=definition.id,
            entitlement_id=entitlement.id,
            component_code=definition.code,
            component_version=definition.version,
            blueprint_ref=definition.default_blueprint_ref,
            status=payload.get("status") or "ready",
            progress=float(payload.get("progress") or 0),
            health=float(payload.get("health") or 0),
            current_phase=payload.get("current_phase") or "ready",
            limits_consumed_json=payload.get("limits_consumed") or {},
            milestones_json=payload.get("milestones") or [],
            tasks_json=payload.get("tasks") or [],
        )
        db.add(instance)
        db.flush()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="component_instance",
            aggregate_id=instance.id,
            event_type="component_instance.created",
            correlation_id=correlation_id,
            payload={"summary": f"Component instance created: {definition.name}", "component_code": definition.code},
        )
        return instance

    def transition_component(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        component_instance_id: str,
        status: str,
        idempotency_key: str,
        reason: str = "",
    ) -> ComponentInstance:
        instance = self._component_or_404(db, tenant_id, component_instance_id)
        capability = "component.start" if status == "active" else "component.view"
        require_entitlement(db, tenant_id=tenant_id, component_code=instance.component_code, capability=capability)
        if instance.status == status:
            return instance
        instance.status = status
        instance.updated_at = utcnow()
        if status == "active" and not instance.started_at:
            instance.started_at = utcnow()
        if status == "completed":
            instance.progress = 100.0
            instance.completed_at = utcnow()
        if status == "blocked":
            instance.blocked_reason = reason or "Blocked by operator"
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="component_instance",
            aggregate_id=instance.id,
            event_type=f"component_instance.{status}",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={"summary": f"Component status changed to {status}", "component_code": instance.component_code, "reason": reason},
        )
        return instance

    def list_approvals(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return models_to_dict(db.query(Approval).filter_by(tenant_id=tenant_id).order_by(Approval.created_at.desc()).all())

    def decide_approval(
        self,
        db: Session,
        tenant_id: str,
        actor_user_id: str,
        correlation_id: str,
        approval_id: str,
        decision: str,
        comment: str,
        idempotency_key: str,
    ) -> Approval:
        approval = db.query(Approval).filter_by(id=approval_id, tenant_id=tenant_id).first()
        if not approval:
            raise DomainError(404, "APPROVAL_NOT_FOUND", "Approval not found")
        if approval.status in {"approved", "rejected"}:
            return approval
        approval.status = "approved" if decision == "approve" else "rejected"
        approval.decision = decision
        approval.comments = comment
        approval.decided_at = utcnow()
        approval.updated_at = utcnow()
        actor_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            aggregate_type="approval",
            aggregate_id=approval.id,
            event_type=f"approval.{approval.status}",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={"summary": f"Approval {approval.status}: {approval.title}", "comment": comment},
        )
        if approval.resource_type == "component_instance":
            instance = db.query(ComponentInstance).filter_by(id=approval.resource_id, tenant_id=tenant_id).first()
            if instance:
                self._recalculate_project_health(db, tenant_id, instance.project_id, approvals_sla=100.0 if approval.status == "approved" else 50.0)
        return approval

    def component_definitions(self, db: Session) -> List[Dict[str, Any]]:
        ensure_component_definitions(db)
        return models_to_dict(db.query(ComponentDefinition).order_by(ComponentDefinition.code.asc()).all())

    def get_component_instance(self, db: Session, tenant_id: str, component_instance_id: str) -> Dict[str, Any]:
        return self._component_bundle(db, self._component_or_404(db, tenant_id, component_instance_id))

    def audit_events(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return models_to_dict(db.query(AuditProjection).filter_by(tenant_id=tenant_id).order_by(AuditProjection.created_at.desc()).limit(100).all())

    def activity(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        return models_to_dict(db.query(AuditProjection).filter_by(tenant_id=tenant_id).order_by(AuditProjection.created_at.desc()).limit(20).all())

    def _program_or_404(self, db: Session, tenant_id: str, program_id: str) -> Program:
        program = db.query(Program).filter_by(id=program_id, tenant_id=tenant_id).first()
        if not program:
            raise DomainError(404, "PROGRAM_NOT_FOUND", "Program not found")
        return program

    def _project_or_404(self, db: Session, tenant_id: str, project_id: str) -> Project:
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first()
        if not project:
            raise DomainError(404, "PROJECT_NOT_FOUND", "Project not found")
        return project

    def _contract_or_404(self, db: Session, tenant_id: str, contract_id: str) -> Contract:
        contract = db.query(Contract).filter_by(id=contract_id, tenant_id=tenant_id).first()
        if not contract:
            raise DomainError(404, "CONTRACT_NOT_FOUND", "Contract not found")
        return contract

    def _component_or_404(self, db: Session, tenant_id: str, component_instance_id: str) -> ComponentInstance:
        instance = db.query(ComponentInstance).filter_by(id=component_instance_id, tenant_id=tenant_id).first()
        if not instance:
            raise DomainError(404, "COMPONENT_INSTANCE_NOT_FOUND", "Component instance not found")
        return instance

    def _program_bundle(self, db: Session, program: Program) -> Dict[str, Any]:
        projects = db.query(Project).filter_by(tenant_id=program.tenant_id, program_id=program.id).all()
        contracts = db.query(Contract).filter_by(tenant_id=program.tenant_id).all()
        components = (
            db.query(ComponentInstance)
            .filter(ComponentInstance.tenant_id == program.tenant_id)
            .filter(ComponentInstance.project_id.in_([project.id for project in projects] or [""]))
            .all()
        )
        scores = db.query(Score).filter_by(tenant_id=program.tenant_id, scope_type="program", scope_id=program.id).order_by(Score.created_at.desc()).all()
        return {
            **model_to_dict(program),
            "projects": models_to_dict(projects),
            "contracts": models_to_dict(contracts),
            "components": [self._component_bundle(db, component) for component in components],
            "scores": models_to_dict(scores),
        }

    def _project_bundle(self, db: Session, project: Project) -> Dict[str, Any]:
        components = db.query(ComponentInstance).filter_by(tenant_id=project.tenant_id, project_id=project.id).all()
        scores = db.query(Score).filter_by(tenant_id=project.tenant_id, scope_type="project", scope_id=project.id).order_by(Score.created_at.desc()).all()
        return {**model_to_dict(project), "components": [self._component_bundle(db, item) for item in components], "scores": models_to_dict(scores)}

    def _component_bundle(self, db: Session, component: ComponentInstance) -> Dict[str, Any]:
        definition = db.query(ComponentDefinition).filter_by(id=component.component_definition_id).first()
        entitlement = db.query(Entitlement).filter_by(id=component.entitlement_id, tenant_id=component.tenant_id).first() if component.entitlement_id else None
        approvals = db.query(Approval).filter_by(tenant_id=component.tenant_id, resource_type="component_instance", resource_id=component.id).all()
        events = db.query(AuditProjection).filter_by(tenant_id=component.tenant_id, resource_type="component_instance", resource_id=component.id).order_by(AuditProjection.created_at.desc()).limit(20).all()
        return {
            **model_to_dict(component),
            "definition": model_to_dict(definition) if definition else None,
            "entitlement": model_to_dict(entitlement) if entitlement else None,
            "approvals": models_to_dict(approvals),
            "events": models_to_dict(events),
        }

    def _program_id_for_component(self, db: Session, component: ComponentInstance) -> Optional[str]:
        project = db.query(Project).filter_by(id=component.project_id, tenant_id=component.tenant_id).first()
        return project.program_id if project else None

    def _recalculate_project_health(self, db: Session, tenant_id: str, project_id: str, approvals_sla: float) -> None:
        components = db.query(ComponentInstance).filter_by(tenant_id=tenant_id, project_id=project_id).all()
        average_progress = sum(item.progress for item in components) / len(components) if components else 0.0
        inputs = {
            "data_completeness": 72.0,
            "operational_progress": average_progress,
            "quality": 82.0,
            "participation": 75.0,
            "risks_resolved": 60.0,
            "approvals_sla": approvals_sla,
        }
        result = self.calculation_engine.calculate("project_health", "project_health@1.0", inputs)
        db.add(
            Score(
                id=new_id(),
                tenant_id=tenant_id,
                scope_type="project",
                scope_id=project_id,
                metric="project_health",
                value=result.value,
                formula_version=result.formula_version,
                inputs_json=inputs,
                explanation_json=result.explanation,
            )
        )
        project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first()
        if project and project.program_id:
            db.add(
                Score(
                    id=new_id(),
                    tenant_id=tenant_id,
                    scope_type="program",
                    scope_id=project.program_id,
                    metric="project_health",
                    value=result.value,
                    formula_version=result.formula_version,
                    inputs_json=inputs,
                    explanation_json=result.explanation,
                )
            )
