from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import SessionLocal, get_db, set_tenant_context
from app.models import (
    Approval,
    ApprovalRequest,
    AgentRunState,
    ComponentInstance,
    GamificationEvent,
    KnowledgeBase,
    KnowledgeDocument,
    LedgerRecord,
    Membership,
    ModelCall,
    Tenant,
    WorkflowRun,
    Engagement,
    OfferingVersion,
    ServiceDeliverable,
    ServiceWorkItem,
)
from app.schemas.operational import MetricValue, OverviewResponse, PortfolioResponse, TenantSummary
from app.schemas.service_delivery_os import CapacityResponse, ServicePortfolioClient, ServicePortfolioResponse
from app.core.config import get_settings
from app.services.serialization import models_to_dict


OPERATOR_ROLES = (
    "owner",
    "super_admin",
    "tenant_admin",
    "engagement_manager",
    "consultant",
    "admin",
    "operator",
)
ACTIVE_RUN_STATUSES = {
    "scheduled",
    "temporal_dispatch_pending",
    "running",
    "pending",
    "waiting_for_human",
    "cancel_requested",
}
LEVELS = [
    (1, "Iniciação", 0),
    (2, "Operação", 100),
    (3, "Orquestração", 300),
    (4, "Homologação", 700),
    (5, "Excelência", 1500),
]

router = APIRouter(prefix="/api/v1/operator", tags=["operator"])


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _level_name(xp: int) -> str:
    return next(name for _number, name, threshold in reversed(LEVELS) if xp >= threshold)


def _summary(db: Session, tenant: Tenant, role: str) -> TenantSummary:
    now = datetime.utcnow().isoformat()
    runs = db.query(WorkflowRun).filter_by(tenant_id=tenant.id).order_by(WorkflowRun.created_at.desc()).all()
    active_runs = [run for run in runs if run.status in ACTIVE_RUN_STATUSES]
    service_approvals = db.query(Approval).filter_by(tenant_id=tenant.id, status="pending").all()
    run_approvals = db.query(ApprovalRequest).filter_by(tenant_id=tenant.id, status="pending").all()
    blocked = db.query(ComponentInstance).filter_by(tenant_id=tenant.id, status="blocked").all()
    latest_hrs_run = next((run for run in runs if run.homologation_readiness_score is not None), None)
    priced_model_calls = (
        db.query(ModelCall)
        .filter(ModelCall.tenant_id == tenant.id, ModelCall.status == "success", ModelCall.estimated_cost_usd > 0)
        .order_by(ModelCall.created_at.desc())
        .limit(100)
        .all()
    )
    model_cost = sum(call.estimated_cost_usd for call in priced_model_calls) if priced_model_calls else None
    model_call_ids = [call.id for call in priced_model_calls]
    xp = int(db.query(func.coalesce(func.sum(GamificationEvent.points), 0)).filter_by(tenant_id=tenant.id).scalar() or 0)
    last_event = db.query(LedgerRecord).filter_by(tenant_id=tenant.id).order_by(LedgerRecord.tenant_sequence.desc()).first()

    next_action = None
    if run_approvals:
        approval = run_approvals[0]
        next_action = {
            "kind": "approval",
            "title": approval.title,
            "resource_id": approval.id,
            "href": f"/approvals?item={approval.id}&kind=run",
        }
    elif service_approvals:
        approval = service_approvals[0]
        next_action = {
            "kind": "approval",
            "title": approval.title,
            "resource_id": approval.id,
            "href": f"/approvals?item={approval.id}&kind=service",
        }
    elif blocked:
        component = blocked[0]
        next_action = {
            "kind": "blocker",
            "title": component.blocked_reason or component.component_code,
            "resource_id": component.id,
            "href": f"/components/{component.id}",
        }
    elif active_runs:
        run = active_runs[0]
        next_action = {
            "kind": "run",
            "title": run.current_node or run.current_phase,
            "resource_id": run.id,
            "href": f"/runs/{run.id}",
        }

    return TenantSummary(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_status=tenant.status,
        role=role,
        active_runs=len(active_runs),
        pending_approvals=len(service_approvals) + len(run_approvals),
        blocked_items=len(blocked),
        knowledge_bases=db.query(KnowledgeBase).filter_by(tenant_id=tenant.id, status="active").count(),
        knowledge_documents=db.query(KnowledgeDocument).filter_by(tenant_id=tenant.id, status="ready").count(),
        hrs=MetricValue(
            value=float(latest_hrs_run.homologation_readiness_score) if latest_hrs_run else None,
            unit="score_0_100",
            provenance="calculated",
            as_of=_iso(latest_hrs_run.updated_at) or now if latest_hrs_run else now,
            source_refs=[latest_hrs_run.id] if latest_hrs_run else [],
        ),
        model_cost_usd=MetricValue(
            value=float(model_cost) if model_cost is not None else None,
            unit="USD",
            provenance="estimated_from_real_usage",
            as_of=now,
            source_refs=model_call_ids,
        ),
        maturity_level=_level_name(xp),
        maturity_xp=xp,
        next_action=next_action,
        last_event_at=_iso(last_event.created_at) if last_event else None,
    )


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .execution_options(include_all_tenants=True)
        .all()
    )
    memberships = [membership for membership in memberships if membership.role in OPERATOR_ROLES]
    clients = []
    for membership in memberships:
        tenant_db = SessionLocal()
        try:
            set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
            tenant = tenant_db.get(Tenant, membership.tenant_id)
            if tenant and tenant.status != "deleted":
                clients.append(_summary(tenant_db, tenant, membership.role))
        finally:
            tenant_db.close()
    clients.sort(key=lambda item: (item.next_action is None, item.tenant_name.lower()))
    return PortfolioResponse(generated_at=datetime.utcnow().isoformat(), clients=clients)


@router.get("/overview", response_model=OverviewResponse)
def overview(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, principal.tenant_id)
    recent = (
        db.query(LedgerRecord)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(LedgerRecord.tenant_sequence.desc())
        .limit(20)
        .all()
    )
    return OverviewResponse(
        generated_at=datetime.utcnow().isoformat(),
        client=_summary(db, tenant, principal.role),
        recent_events=models_to_dict(recent),
    )


@router.get("/agents")
def agent_operations(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    states = (
        db.query(AgentRunState)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(AgentRunState.updated_at.desc())
        .limit(250)
        .all()
    )
    run_ids = {state.run_id for state in states}
    runs = db.query(WorkflowRun).filter(WorkflowRun.tenant_id == principal.tenant_id, WorkflowRun.id.in_(run_ids)).all() if run_ids else []
    run_by_id = {run.id: run for run in runs}
    return {
        "states": [
            {
                **models_to_dict([state])[0],
                "run": {
                    "id": run_by_id[state.run_id].id,
                    "status": run_by_id[state.run_id].status,
                    "current_phase": run_by_id[state.run_id].current_phase,
                } if state.run_id in run_by_id else None,
            }
            for state in states
        ]
    }


def _service_summary(db: Session, tenant: Tenant, role: str) -> ServicePortfolioClient:
    engagements = db.query(Engagement).filter_by(tenant_id=tenant.id).all()
    deliverables = db.query(ServiceDeliverable).filter_by(tenant_id=tenant.id).all()
    work_items = db.query(ServiceWorkItem).filter_by(tenant_id=tenant.id).all()
    pending_approvals = db.query(Approval).filter_by(tenant_id=tenant.id, status="pending").count()
    pending_run_approvals = db.query(ApprovalRequest).filter_by(tenant_id=tenant.id, status="pending").count()
    runs = db.query(WorkflowRun).filter_by(tenant_id=tenant.id).order_by(WorkflowRun.created_at.desc()).all()
    priced_calls = db.query(ModelCall).filter(
        ModelCall.tenant_id == tenant.id,
        ModelCall.status == "success",
        ModelCall.estimated_cost_usd > 0,
    ).all()
    unfinished = [item for item in deliverables if item.status not in {"approved", "delivered", "cancelled"}]
    now = datetime.utcnow()
    next_deliverable = min((item for item in unfinished if item.due_at), key=lambda item: item.due_at, default=None)
    latest_hrs = next((run for run in runs if run.homologation_readiness_score is not None), None)
    offering_ids = {item.offering_version_id for item in engagements}
    return ServicePortfolioClient(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=role,
        active_engagements=sum(item.status == "active" for item in engagements),
        contracted_offerings=len(offering_ids),
        deliverables_due=len([item for item in unfinished if item.due_at]),
        deliverables_at_risk=len([item for item in unfinished if item.due_at and item.due_at < now]),
        deliverables_in_review=sum(item.status == "review_ready" for item in deliverables),
        deliverables_completed=sum(item.status in {"approved", "delivered"} for item in deliverables),
        active_work_items=sum(item.status == "in_progress" for item in work_items),
        pending_approvals=pending_approvals + pending_run_approvals,
        active_runs=sum(run.status in ACTIVE_RUN_STATUSES for run in runs),
        model_cost_usd=sum(float(call.estimated_cost_usd or 0) for call in priced_calls) if priced_calls else None,
        latest_hrs=float(latest_hrs.homologation_readiness_score) if latest_hrs else None,
        next_commitment={
            "kind": "deliverable",
            "title": next_deliverable.title,
            "resource_id": next_deliverable.id,
            "due_at": next_deliverable.due_at.isoformat(),
            "href": f"/deliverables/{next_deliverable.id}",
        } if next_deliverable else None,
    )


def _operator_tenant_sessions(principal: Principal, db: Session):
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .execution_options(include_all_tenants=True)
        .all()
    )
    return [membership for membership in memberships if membership.role in OPERATOR_ROLES]


@router.get("/service-portfolio", response_model=ServicePortfolioResponse)
def service_portfolio(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    clients = []
    for membership in _operator_tenant_sessions(principal, db):
        tenant_db = SessionLocal()
        try:
            set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
            tenant = tenant_db.get(Tenant, membership.tenant_id)
            if tenant and tenant.status != "deleted":
                clients.append(_service_summary(tenant_db, tenant, membership.role))
        finally:
            tenant_db.close()
    clients.sort(key=lambda item: (-item.deliverables_at_risk, item.next_commitment is None, item.tenant_name.casefold()))
    return ServicePortfolioResponse(generated_at=datetime.utcnow(), clients=clients)


@router.get("/work-queue")
def operator_work_queue(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    rows = []
    for membership in _operator_tenant_sessions(principal, db):
        tenant_db = SessionLocal()
        try:
            set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
            tenant = tenant_db.get(Tenant, membership.tenant_id)
            items = tenant_db.query(ServiceWorkItem).filter(
                ServiceWorkItem.tenant_id == membership.tenant_id,
                ServiceWorkItem.status.in_(["blocked", "in_progress", "queued"]),
            ).all()
            for item in items:
                engagement = tenant_db.query(Engagement).filter_by(id=item.engagement_id, tenant_id=membership.tenant_id).first()
                rows.append({
                    "id": item.id,
                    "tenant_id": membership.tenant_id,
                    "tenant_name": tenant.name if tenant else membership.tenant_id,
                    "engagement_id": item.engagement_id,
                    "engagement_name": engagement.name if engagement else "",
                    "title": item.title,
                    "status": item.status,
                    "priority": item.priority,
                    "due_at": _iso(item.due_at),
                    "blocked_reason": item.blocked_reason,
                    "record_version": item.record_version,
                })
        finally:
            tenant_db.close()
    rows.sort(key=lambda item: (
        item["status"] != "blocked",
        priority_order.get(item["priority"], 9),
        item["due_at"] or "9999-12-31",
    ))
    return {"generated_at": datetime.utcnow().isoformat(), "items": rows}


@router.get("/capacity", response_model=CapacityResponse)
def operator_capacity(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    tenants = []
    conflicts = []
    active_total = 0
    for membership in _operator_tenant_sessions(principal, db):
        tenant_db = SessionLocal()
        try:
            set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
            tenant = tenant_db.get(Tenant, membership.tenant_id)
            active = tenant_db.query(ServiceWorkItem).filter_by(tenant_id=membership.tenant_id, status="in_progress").count()
            queued = tenant_db.query(ServiceWorkItem).filter_by(tenant_id=membership.tenant_id, status="queued").count()
            blocked = tenant_db.query(ServiceWorkItem).filter_by(tenant_id=membership.tenant_id, status="blocked").count()
            active_total += active
            item = {
                "tenant_id": membership.tenant_id,
                "tenant_name": tenant.name if tenant else membership.tenant_id,
                "active": active,
                "queued": queued,
                "blocked": blocked,
                "limit": settings.service_wip_per_tenant_limit,
                "over_capacity": active > settings.service_wip_per_tenant_limit,
            }
            tenants.append(item)
            if item["over_capacity"]:
                conflicts.append({"type": "tenant_wip", **item})
        finally:
            tenant_db.close()
    if active_total > settings.service_wip_global_limit:
        conflicts.insert(0, {"type": "global_wip", "active": active_total, "limit": settings.service_wip_global_limit})
    return CapacityResponse(
        generated_at=datetime.utcnow(),
        global_limit=settings.service_wip_global_limit,
        active_total=active_total,
        available_slots=max(0, settings.service_wip_global_limit - active_total),
        over_capacity=active_total > settings.service_wip_global_limit,
        per_tenant_limit=settings.service_wip_per_tenant_limit,
        tenants=tenants,
        conflicts=conflicts,
    )
