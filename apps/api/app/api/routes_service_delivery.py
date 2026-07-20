import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.service_delivery.commands import begin_command, complete_command
from app.service_delivery.mvp_factory import MvpFactoryService
from app.service_delivery.service import DomainError, ServiceDeliveryService, actor_event, require_entitlement, require_limit
from app.services.run_service import provider
from app.services.serialization import model_to_dict
from app.workflow.temporal_outbox import enqueue_signal, enqueue_start

router = APIRouter(prefix="/api/v1", tags=["service-delivery"])
OPERATIONAL_ROLES = ("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
get_current_principal = require_roles(*OPERATIONAL_ROLES)
service = ServiceDeliveryService()
mvp_service = MvpFactoryService()


class CommandPayload(BaseModel):
    reason: str = ""
    comment: str = ""


class ProgramPayload(BaseModel):
    name: str
    description: str = ""
    sponsor: str = ""
    status: str = "active"
    start_date: str = ""
    target_end_date: str = ""


class ContractPayload(BaseModel):
    contract_number: str = ""
    status: str = "draft"
    valid_from: str = ""
    valid_until: str = ""
    commercial_metadata: Dict[str, Any] = Field(default_factory=dict)
    scope_summary: str = ""


class EntitlementPayload(BaseModel):
    component_code: str
    component_version: str = "1.0"
    status: str = "granted"
    valid_from: str = ""
    valid_until: str = ""
    limits: Dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    terms: Dict[str, Any] = Field(default_factory=dict)


class ComponentPayload(BaseModel):
    component_code: str
    status: str = "ready"
    progress: float = 0.0
    health: float = 0.0
    current_phase: str = ""
    limits_consumed: Dict[str, Any] = Field(default_factory=dict)
    milestones: list[Dict[str, Any]] = Field(default_factory=list)
    tasks: list[Dict[str, Any]] = Field(default_factory=list)


class DecisionPayload(BaseModel):
    comment: str = ""


class ProspectPayload(BaseModel):
    name: str = ""
    company: str = ""
    sector: str = ""
    contact_email: str = ""
    source: str = "manual"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OpportunityPayload(BaseModel):
    prospect_id: str
    title: str = ""
    summary: str = ""
    program_id: str = ""
    project_id: str = ""
    component_instance_id: str = ""
    value_potential: float = 0.0


class BriefingPayload(BaseModel):
    raw_text: str


class OpportunityApprovalPayload(BaseModel):
    comment: str


class DeliveryConversionPayload(BaseModel):
    confirmation: str


class ProspectBatchPayload(BaseModel):
    prospects: list[Dict[str, Any]] = Field(default_factory=list)


def _correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or "api-v1"


def _idempotency_key(request: Request) -> str:
    return request.headers.get("Idempotency-Key") or ""


def _required_idempotency_key(request: Request) -> str:
    key = _idempotency_key(request).strip()
    if not key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
    return key


@router.get("/dashboard")
def dashboard(principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")), db: Session = Depends(get_db)):
    return service.dashboard(db, principal.tenant_id)


@router.get("/dashboard/activity")
def dashboard_activity(principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")), db: Session = Depends(get_db)):
    return service.activity(db, principal.tenant_id)


@router.get("/programs")
def list_programs(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return service.list_programs(db, principal.tenant_id)


@router.post("/programs")
def create_program(
    payload: ProgramPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager")),
    db: Session = Depends(get_db),
):
    program = service.create_program(db, principal.tenant_id, principal.user_id, _correlation_id(request), payload.model_dump())
    db.commit()
    db.refresh(program)
    return model_to_dict(program)


@router.get("/programs/{program_id}")
def get_program(program_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return service.get_program(db, principal.tenant_id, program_id)


@router.get("/programs/{program_id}/projects")
def program_projects(program_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return service.list_program_projects(db, principal.tenant_id, program_id)


@router.get("/contracts")
def list_contracts(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import Contract
    from app.services.serialization import models_to_dict

    return models_to_dict(db.query(Contract).filter_by(tenant_id=principal.tenant_id).order_by(Contract.created_at.desc()).all())


@router.get("/entitlements")
def list_entitlements(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import Entitlement
    from app.services.serialization import models_to_dict

    return models_to_dict(db.query(Entitlement).filter_by(tenant_id=principal.tenant_id).order_by(Entitlement.created_at.desc()).all())


@router.post("/contracts")
def create_contract(
    payload: ContractPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin")),
    db: Session = Depends(get_db),
):
    contract = service.create_contract(db, principal.tenant_id, principal.user_id, _correlation_id(request), payload.model_dump())
    db.commit()
    db.refresh(contract)
    return model_to_dict(contract)


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import Contract

    contract = db.query(Contract).filter_by(id=contract_id, tenant_id=principal.tenant_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail={"code": "CONTRACT_NOT_FOUND", "message": "Contract not found"})
    return model_to_dict(contract)


@router.post("/contracts/{contract_id}/activate")
def activate_contract(
    contract_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin")),
    db: Session = Depends(get_db),
):
    contract = service.activate_contract(db, principal.tenant_id, principal.user_id, _correlation_id(request), contract_id, _idempotency_key(request))
    db.commit()
    db.refresh(contract)
    return model_to_dict(contract)


@router.post("/contracts/{contract_id}/entitlements")
def create_entitlement(
    contract_id: str,
    payload: EntitlementPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin")),
    db: Session = Depends(get_db),
):
    entitlement = service.add_entitlement(db, principal.tenant_id, principal.user_id, _correlation_id(request), contract_id, payload.model_dump())
    db.commit()
    db.refresh(entitlement)
    return model_to_dict(entitlement)


@router.post("/entitlements/{entitlement_id}/grant")
def grant_entitlement(
    entitlement_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin")),
    db: Session = Depends(get_db),
):
    entitlement = service.set_entitlement_status(db, principal.tenant_id, principal.user_id, _correlation_id(request), entitlement_id, "granted", _idempotency_key(request))
    db.commit()
    db.refresh(entitlement)
    return model_to_dict(entitlement)


@router.post("/entitlements/{entitlement_id}/suspend")
def suspend_entitlement(
    entitlement_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin")),
    db: Session = Depends(get_db),
):
    entitlement = service.set_entitlement_status(db, principal.tenant_id, principal.user_id, _correlation_id(request), entitlement_id, "suspended", _idempotency_key(request))
    db.commit()
    db.refresh(entitlement)
    return model_to_dict(entitlement)


@router.get("/component-definitions")
def component_definitions(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return service.component_definitions(db)


@router.get("/component-instances")
def list_component_instances(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import ComponentDefinition, ComponentInstance, Project

    rows = (
        db.query(ComponentInstance)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(ComponentInstance.created_at.desc())
        .all()
    )
    response = []
    for row in rows:
        item = model_to_dict(row)
        item["definition"] = model_to_dict(db.get(ComponentDefinition, row.component_definition_id))
        item["project"] = model_to_dict(db.get(Project, row.project_id))
        response.append(item)
    return response


@router.get("/component-instances/{component_instance_id}")
def component_instance(component_instance_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return service.get_component_instance(db, principal.tenant_id, component_instance_id)


@router.post("/projects/{project_id}/components")
def create_component(
    project_id: str,
    payload: ComponentPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    component = service.create_component_instance(db, principal.tenant_id, principal.user_id, _correlation_id(request), project_id, payload.model_dump())
    db.commit()
    db.refresh(component)
    return model_to_dict(component)


def _transition(component_instance_id: str, status: str, payload: CommandPayload, request: Request, principal: Principal, db: Session):
    component = service.transition_component(db, principal.tenant_id, principal.user_id, _correlation_id(request), component_instance_id, status, _idempotency_key(request), payload.reason)
    db.commit()
    db.refresh(component)
    return model_to_dict(component)


@router.post("/component-instances/{component_instance_id}/start")
def start_component(component_instance_id: str, payload: CommandPayload, request: Request, principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")), db: Session = Depends(get_db)):
    return _transition(component_instance_id, "active", payload, request, principal, db)


@router.post("/component-instances/{component_instance_id}/block")
def block_component(component_instance_id: str, payload: CommandPayload, request: Request, principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")), db: Session = Depends(get_db)):
    return _transition(component_instance_id, "blocked", payload, request, principal, db)


@router.post("/component-instances/{component_instance_id}/complete")
def complete_component(component_instance_id: str, payload: CommandPayload, request: Request, principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")), db: Session = Depends(get_db)):
    return _transition(component_instance_id, "completed", payload, request, principal, db)


@router.get("/approvals")
def approvals(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return service.list_approvals(db, principal.tenant_id)


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: str,
    payload: DecisionPayload,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    approval = service.decide_approval(db, principal.tenant_id, principal.user_id, _correlation_id(request), approval_id, "approve", payload.comment, _idempotency_key(request))
    db.commit()
    db.refresh(approval)
    return model_to_dict(approval)


@router.post("/approvals/{approval_id}/reject")
def reject(
    approval_id: str,
    payload: DecisionPayload,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    approval = service.decide_approval(db, principal.tenant_id, principal.user_id, _correlation_id(request), approval_id, "reject", payload.comment, _idempotency_key(request))
    db.commit()
    db.refresh(approval)
    return model_to_dict(approval)


@router.get("/audit-events")
def audit_events(principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")), db: Session = Depends(get_db)):
    return service.audit_events(db, principal.tenant_id)


@router.get("/prospects")
def list_prospects(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return mvp_service.list_prospects(db, principal.tenant_id)


@router.post("/prospects")
def create_prospect(
    payload: ProspectPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    prospect = mvp_service.create_prospect(db, principal.tenant_id, principal.user_id, _correlation_id(request), payload.model_dump())
    db.commit()
    db.refresh(prospect)
    return model_to_dict(prospect)


@router.get("/opportunities")
def list_opportunities(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return mvp_service.list_opportunities(db, principal.tenant_id)


@router.post("/opportunities")
def create_opportunity(
    payload: OpportunityPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    opportunity = mvp_service.create_opportunity(db, principal.tenant_id, principal.user_id, _correlation_id(request), payload.model_dump())
    db.commit()
    db.refresh(opportunity)
    return model_to_dict(opportunity)


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return mvp_service.get_opportunity(db, principal.tenant_id, opportunity_id)


@router.post("/opportunities/{opportunity_id}/briefing")
def add_briefing(
    opportunity_id: str,
    payload: BriefingPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    briefing = mvp_service.add_briefing(db, principal.tenant_id, principal.user_id, _correlation_id(request), opportunity_id, payload.raw_text)
    db.commit()
    db.refresh(briefing)
    return model_to_dict(briefing)


@router.post("/opportunities/{opportunity_id}/validate")
def validate_opportunity(
    opportunity_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    opportunity = mvp_service.validate_idea(db, principal.tenant_id, principal.user_id, _correlation_id(request), opportunity_id)
    db.commit()
    db.refresh(opportunity)
    return model_to_dict(opportunity)


@router.post("/opportunities/{opportunity_id}/scope-mvp")
def scope_mvp(
    opportunity_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    spec = mvp_service.scope_mvp(db, principal.tenant_id, principal.user_id, _correlation_id(request), opportunity_id)
    db.commit()
    db.refresh(spec)
    return model_to_dict(spec)


@router.post("/opportunities/{opportunity_id}/generate-mvp")
def generate_mvp(
    opportunity_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    mvp_run = mvp_service.generate_mvp(db, principal.tenant_id, principal.user_id, _correlation_id(request), opportunity_id)
    db.commit()
    db.refresh(mvp_run)
    return model_to_dict(mvp_run)


@router.post("/opportunities/{opportunity_id}/generate-proposal")
def generate_proposal(
    opportunity_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="opportunity.generate_proposal",
        idempotency_key=key,
        request_payload={"opportunity_id": opportunity_id},
    )
    if cached is not None:
        return cached
    proposal = mvp_service.generate_proposal(
        db, principal.tenant_id, principal.user_id, _correlation_id(request), opportunity_id, f"proposal:{key}"
    )
    response = model_to_dict(proposal)
    complete_command(db, receipt, response=response, resource_type="commercial_proposal", resource_id=proposal.id)
    db.commit()
    return response


@router.post("/opportunities/{opportunity_id}/approve")
def approve_opportunity(
    opportunity_id: str,
    payload: OpportunityApprovalPayload,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="opportunity.approve",
        idempotency_key=key,
        request_payload={"opportunity_id": opportunity_id, **payload.model_dump()},
    )
    if cached is not None:
        return cached
    opportunity = mvp_service.approve_opportunity(
        db,
        principal.tenant_id,
        principal.user_id,
        _correlation_id(request),
        opportunity_id,
        payload.comment,
        f"opportunity-approve:{key}",
    )
    response = model_to_dict(opportunity)
    complete_command(db, receipt, response=response, resource_type="opportunity", resource_id=opportunity.id)
    db.commit()
    return response


@router.post("/opportunities/{opportunity_id}/convert-to-delivery")
def convert_opportunity_to_delivery(
    opportunity_id: str,
    payload: DeliveryConversionPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager")),
    db: Session = Depends(get_db),
):
    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="opportunity.convert_to_delivery",
        idempotency_key=key,
        request_payload={"opportunity_id": opportunity_id, **payload.model_dump()},
    )
    if cached is not None:
        return cached
    response = mvp_service.convert_to_delivery(
        db,
        principal.tenant_id,
        principal.user_id,
        _correlation_id(request),
        opportunity_id,
        payload.confirmation,
        f"opportunity-convert:{key}",
    )
    complete_command(db, receipt, response=response, resource_type="opportunity", resource_id=opportunity_id)
    db.commit()
    return response


@router.get("/mvp-runs")
def list_mvp_runs(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import MvpRun, Opportunity

    rows = (
        db.query(MvpRun)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(MvpRun.created_at.desc())
        .all()
    )
    response = []
    for row in rows:
        item = model_to_dict(row)
        item["opportunity"] = model_to_dict(db.get(Opportunity, row.opportunity_id))
        response.append(item)
    return response


@router.get("/mvp-runs/{mvp_run_id}")
def get_mvp_run(mvp_run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return mvp_service.get_mvp_run(db, principal.tenant_id, mvp_run_id)


def _decide_mvp(mvp_run_id: str, decision: str, payload: DecisionPayload, request: Request, principal: Principal, db: Session):
    mvp_run = mvp_service.decide_mvp_run(db, principal.tenant_id, principal.user_id, _correlation_id(request), mvp_run_id, decision, payload.comment)
    db.commit()
    db.refresh(mvp_run)
    return model_to_dict(mvp_run)


@router.post("/mvp-runs/{mvp_run_id}/approve")
def approve_mvp_run(mvp_run_id: str, payload: DecisionPayload, request: Request, principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)), db: Session = Depends(get_db)):
    return _decide_mvp(mvp_run_id, "approve", payload, request, principal, db)


@router.post("/mvp-runs/{mvp_run_id}/reject")
def reject_mvp_run(mvp_run_id: str, payload: DecisionPayload, request: Request, principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)), db: Session = Depends(get_db)):
    return _decide_mvp(mvp_run_id, "reject", payload, request, principal, db)


@router.post("/mvp-runs/{mvp_run_id}/request-changes")
def request_mvp_changes(mvp_run_id: str, payload: DecisionPayload, request: Request, principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)), db: Session = Depends(get_db)):
    return _decide_mvp(mvp_run_id, "request_changes", payload, request, principal, db)


@router.get("/mvp-runs/{mvp_run_id}/package")
def get_mvp_package(mvp_run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return mvp_service.get_mvp_package(db, principal.tenant_id, mvp_run_id)


@router.post("/mvp-runs/{mvp_run_id}/create-asf-run")
async def create_asf_run(
    mvp_run_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    from app.agents.ai_native_executor import AI_NATIVE_WORKFLOW_ID
    from app.models import CommercialProposal, MvpRun, MvpSpec, Opportunity, WorkflowRun
    from app.service_delivery.capacity import acquire_workflow_slot

    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="mvp_run.create_asf_run",
        idempotency_key=key,
        request_payload={"mvp_run_id": mvp_run_id},
    )
    if cached is not None:
        return cached
    mvp_run = db.query(MvpRun).filter_by(id=mvp_run_id, tenant_id=principal.tenant_id).first()
    if not mvp_run:
        raise DomainError(404, "MVP_RUN_NOT_FOUND", "MVP run not found")
    if mvp_run.status != "approved":
        raise DomainError(409, "MVP_APPROVAL_REQUIRED", "Human approval is required before creating an ASF run")
    spec = db.query(MvpSpec).filter_by(id=mvp_run.mvp_spec_id, tenant_id=principal.tenant_id).first()
    if not spec:
        raise DomainError(409, "MVP_SCOPE_REQUIRED", "An approved MVP scope is required before AI-native execution")
    opportunity = db.query(Opportunity).filter_by(id=mvp_run.opportunity_id, tenant_id=principal.tenant_id).first()
    if not opportunity or opportunity.status != "converted" or not opportunity.project_id or not opportunity.component_instance_id:
        raise DomainError(409, "DELIVERY_CONVERSION_REQUIRED", "Contract, entitlement and component instance are required")
    entitlement = require_entitlement(
        db,
        tenant_id=principal.tenant_id,
        component_code="rapid_mvp_factory",
        capability="asf.run.create",
    )
    tenant_active_runs = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.status.in_(
                ["scheduled", "temporal_dispatch_pending", "running", "pending", "waiting_for_tool", "cancel_requested"]
            )
        )
        .count()
    )
    require_limit(entitlement, "concurrent_workflows", tenant_active_runs)
    retry_of_run_id = None
    if mvp_run.workflow_run_id:
        existing = db.query(WorkflowRun).filter_by(id=mvp_run.workflow_run_id, tenant_id=principal.tenant_id).first()
        if existing and existing.status not in {"failed", "cancelled"}:
            response = model_to_dict(existing)
            complete_command(db, receipt, response=response, resource_type="workflow_run", resource_id=existing.id)
            db.commit()
            return response
        if existing:
            retry_of_run_id = existing.id
    settings = get_settings()
    if not settings.generative_build_enabled:
        raise DomainError(
            409,
            "GENERATIVE_BUILD_DISABLED",
            "AI-native build is disabled; enable it only with a real LiteLLM provider and isolated sandbox",
        )
    proposal = db.query(CommercialProposal).filter_by(
        tenant_id=principal.tenant_id,
        opportunity_id=opportunity.id,
    ).first()
    context_manifest = {
        "mvp_run_id": mvp_run.id,
        "mvp_spec_id": spec.id,
        "opportunity_id": opportunity.id,
        "scope": {
            "blueprint_ref": spec.blueprint_ref,
            "stack": spec.stack,
            "scope": spec.scope_json,
            "acceptance_criteria": spec.acceptance_criteria_json,
            "deliverables": spec.deliverables_json,
        },
        "commercial": {
            "proposal_id": proposal.id if proposal else None,
            "proposal_status": proposal.status if proposal else None,
            "pricing": proposal.pricing_json if proposal else {},
            "contract_id": entitlement.contract_id,
            "entitlement_id": entitlement.id,
            "approved": True,
        },
        "knowledge_base_ids": list((spec.scope_json or {}).get("knowledge_base_ids") or []),
        "retry_of_run_id": retry_of_run_id,
        "workflow_version": "2.13.0",
        "context_policy_version": "2.13.0",
        "cost_policy_version": "2.13.0",
    }
    demand = (
        f"Approved AI-native product mission for opportunity {opportunity.id}: {opportunity.title}.\n"
        f"Business problem: {opportunity.summary}\n"
        "Generate the contracted full-stack product from the approved tenant-scoped context. "
        "Every artifact and file must come from a validated model output; execute only allowlisted tests and gates, "
        "produce traceability and wait for final human approval."
    )
    if settings.workflow_backend.lower() == "temporal":
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            project_id=opportunity.project_id,
            workflow_id=AI_NATIVE_WORKFLOW_ID,
            demand=demand,
            status="scheduled",
            current_phase="temporal_scheduled",
            current_node="Temporal Worker",
            provider="litellm-ai-native-v2",
            generation_mode="ai_native_v2",
            executor_protocol_version="segmented-output-v1",
            trace_id=str(uuid.uuid4()),
            context_manifest_json=context_manifest,
            ai_budget_usd=settings.model_run_budget_usd,
            ai_cost_usd=0.0,
        )
        db.add(run)
        db.flush()
        contracted_limit = int((entitlement.limits_json or {}).get("concurrent_workflows") or 0) or None
        acquire_workflow_slot(db, run.id, tenant_limit=contracted_limit)
        enqueue_start(db, run)
        run.status = "temporal_dispatch_pending"
    else:
        if not hasattr(provider, "start_ai_native_enterprise_run"):
            raise DomainError(500, "AI_NATIVE_PROVIDER_REQUIRED", "Configured provider does not support AI-native execution")
        run = provider.start_ai_native_enterprise_run(
            db,
            demand=demand,
            project_id=opportunity.project_id,
            tenant_id=principal.tenant_id,
            context_manifest=context_manifest,
        )
    mvp_run.workflow_run_id = run.id
    mvp_run.current_phase = "asf_run"
    opportunity.stage = "technical_homologation"
    actor_event(
        db,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        aggregate_type="mvp_run",
        aggregate_id=mvp_run.id,
        event_type="mvp_run.asf_run_created",
        correlation_id=_correlation_id(request),
        idempotency_key=f"asf-run:{key}",
        payload={
            "summary": "Controlled ASF run created from approved package",
            "run_id": run.id,
            "retry_of_run_id": retry_of_run_id,
        },
    )
    response = model_to_dict(run)
    complete_command(db, receipt, response=response, resource_type="workflow_run", resource_id=run.id)
    db.commit()
    return response


@router.post("/prospect-batches")
def create_prospect_batch(
    payload: ProspectBatchPayload,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    result = mvp_service.create_prospect_batch(db, principal.tenant_id, principal.user_id, _correlation_id(request), payload.model_dump())
    db.commit()
    return result


@router.get("/ai-activity")
def ai_activity(principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")), db: Session = Depends(get_db)):
    return mvp_service.ai_activity(db, principal.tenant_id)


@router.get("/deliverables")
def list_deliverables(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    from app.models import HomologationPackage
    from app.services.serialization import models_to_dict

    return models_to_dict(
        db.query(HomologationPackage)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(HomologationPackage.created_at.desc())
        .all()
    )


@router.post("/deliverables/{deliverable_id}/submit-for-approval")
def submit_deliverable_for_approval(
    deliverable_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    from app.models import ApprovalRequest, HomologationPackage, WorkflowRun

    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="deliverable.submit_for_approval",
        idempotency_key=key,
        request_payload={"deliverable_id": deliverable_id},
    )
    if cached is not None:
        return cached
    package = db.query(HomologationPackage).filter_by(id=deliverable_id, tenant_id=principal.tenant_id).first()
    if not package:
        raise DomainError(404, "DELIVERABLE_NOT_FOUND", "Deliverable not found")
    run = db.query(WorkflowRun).filter_by(id=package.run_id, tenant_id=principal.tenant_id).first()
    if not run:
        raise DomainError(404, "RUN_NOT_FOUND", "Owning run not found")
    require_entitlement(db, tenant_id=principal.tenant_id, component_code="rapid_mvp_factory", capability="homologation.package")
    approval = (
        db.query(ApprovalRequest)
        .filter_by(run_id=run.id, tenant_id=principal.tenant_id)
        .order_by(ApprovalRequest.created_at.desc())
        .first()
    )
    if not approval:
        approval = ApprovalRequest(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            run_id=run.id,
            node_id="Human Approval",
            title="Final homologation approval",
            description="Review test evidence, quality gates, traceability and package assumptions.",
            status="pending",
            requested_action="approve_for_delivery",
            risk_level="medium",
        )
        db.add(approval)
    package.status = "submitted_for_approval"
    actor_event(
        db,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        aggregate_type="homologation_package",
        aggregate_id=package.id,
        event_type="deliverable.submitted_for_approval",
        correlation_id=_correlation_id(request),
        idempotency_key=f"deliverable-submit:{key}",
        payload={"summary": "Homologation package submitted for final human approval", "run_id": run.id},
    )
    response = {"deliverable": model_to_dict(package), "approval": model_to_dict(approval)}
    complete_command(db, receipt, response=response, resource_type="homologation_package", resource_id=package.id)
    db.commit()
    return response


@router.post("/deliverables/{deliverable_id}/approve")
async def approve_deliverable(
    deliverable_id: str,
    payload: OpportunityApprovalPayload,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    from app.models import Artifact, ComponentInstance, HomologationPackage, MvpRun, Opportunity, WorkflowRun, utcnow

    if not payload.comment.strip():
        raise DomainError(400, "APPROVAL_REASON_REQUIRED", "A final approval comment is required")
    key = _required_idempotency_key(request)
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="deliverable.approve",
        idempotency_key=key,
        request_payload={"deliverable_id": deliverable_id, **payload.model_dump()},
    )
    if cached is not None:
        return cached
    package = db.query(HomologationPackage).filter_by(id=deliverable_id, tenant_id=principal.tenant_id).first()
    if not package:
        raise DomainError(404, "DELIVERABLE_NOT_FOUND", "Deliverable not found")
    if package.status not in {"created", "submitted_for_approval"}:
        raise DomainError(409, "DELIVERABLE_NOT_APPROVABLE", f"Deliverable cannot be approved from status {package.status}")
    require_entitlement(db, tenant_id=principal.tenant_id, component_code="rapid_mvp_factory", capability="delivery.approve")
    run = db.query(WorkflowRun).filter_by(id=package.run_id, tenant_id=principal.tenant_id).first()
    if not run:
        raise DomainError(404, "RUN_NOT_FOUND", "Owning run not found")
    if get_settings().workflow_backend.lower() == "temporal" and not run.temporal_workflow_id:
        raise DomainError(409, "TEMPORAL_WORKFLOW_REQUIRED", "Temporal workflow id is missing")
    provider.approve_run(db, run.id, payload.comment, commit=False)
    if get_settings().workflow_backend.lower() == "temporal":
        enqueue_signal(
            db,
            run,
            signal_name="human_decision",
            payload={"decision": "approved"},
            decision_key=f"deliverable-approved:{key}",
        )
    package = db.query(HomologationPackage).filter_by(id=deliverable_id, tenant_id=principal.tenant_id).first()
    package.status = "delivered"
    mvp_run = db.query(MvpRun).filter_by(workflow_run_id=run.id, tenant_id=principal.tenant_id).first()
    if mvp_run:
        mvp_run.status = "delivered"
        mvp_run.current_phase = "delivery"
        opportunity = db.query(Opportunity).filter_by(id=mvp_run.opportunity_id, tenant_id=principal.tenant_id).first()
        if opportunity:
            opportunity.status = "delivered"
            opportunity.stage = "assisted_operation"
        component = (
            db.query(ComponentInstance)
            .filter_by(id=mvp_run.component_instance_id, tenant_id=principal.tenant_id)
            .first()
            if mvp_run.component_instance_id
            else None
        )
        if component:
            component.status = "completed"
            component.progress = 100.0
            component.current_phase = "assisted_operation"
            component.completed_at = component.completed_at or utcnow()
    actor_event(
        db,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        aggregate_type="homologation_package",
        aggregate_id=package.id,
        event_type="deliverable.approved_and_delivered",
        correlation_id=_correlation_id(request),
        idempotency_key=f"deliverable-approve:{key}",
        payload={"summary": "Final human approval recorded and delivery released", "run_id": run.id, "comment": payload.comment},
    )
    for artifact in db.query(Artifact).filter(
        Artifact.tenant_id == principal.tenant_id,
        ((Artifact.run_id == run.id) | ((Artifact.mvp_run_id == mvp_run.id) if mvp_run else False)),
    ).all():
        artifact.audience = "client"
    response = {"deliverable": model_to_dict(package), "run": model_to_dict(run)}
    complete_command(db, receipt, response=response, resource_type="homologation_package", resource_id=package.id)
    db.commit()
    return response
