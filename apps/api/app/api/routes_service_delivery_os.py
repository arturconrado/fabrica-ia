import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import SessionLocal, get_db, set_tenant_context
from app.models import LedgerRecord, Membership, ServiceWorkItem
from app.schemas.service_delivery_os import (
    AgentAssignmentCreate,
    AgentCandidateProposal,
    CandidateDecisionRequest,
    CapabilityGapCreate,
    DeliverableDecisionRequest,
    DeliverableDeliveryRequest,
    DeliverableGenerateRequest,
    DeliverableRevisionCreate,
    EngagementActivationRequest,
    EngagementCreate,
    OfferingView,
    OutcomeMetricCreate,
    OutcomeObservationRequest,
    PlanApprovalRequest,
    PlanGenerateRequest,
    WorkItemTransitionRequest,
)
from app.service_delivery.commands import begin_command, complete_command
from app.service_delivery.os_service import ServiceDeliveryOSService
from app.service_delivery.service import DomainError
from app.services.serialization import model_to_dict


router = APIRouter(prefix="/api/v1", tags=["service-delivery-os"])
OPERATIONAL_ROLES = ("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
ADMIN_ROLES = ("owner", "super_admin", "tenant_admin", "admin")
service = ServiceDeliveryOSService()


class SubmitDeliverableRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(default="", max_length=4_000)


def _correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or "service-delivery-os"


def _idempotency_key(request: Request) -> str:
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
    return key


def _command(
    db: Session, principal: Principal, request: Request, name: str, payload: dict[str, Any]
):
    key = _idempotency_key(request)
    receipt, cached = begin_command(
        db, tenant_id=principal.tenant_id, command_name=name,
        idempotency_key=key, request_payload=payload,
    )
    return key, receipt, cached


def _finish(db: Session, receipt, response: dict[str, Any], resource_type: str, resource_id: str):
    complete_command(db, receipt, response=response, resource_type=resource_type, resource_id=resource_id)
    db.commit()
    return response


def _global_active_wip(principal: Principal, db: Session) -> int:
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .execution_options(include_all_tenants=True)
        .all()
    )
    total = 0
    for membership in memberships:
        if membership.role not in OPERATIONAL_ROLES:
            continue
        tenant_db = SessionLocal()
        try:
            set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
            total += tenant_db.query(ServiceWorkItem).filter_by(
                tenant_id=membership.tenant_id, status="in_progress"
            ).count()
        finally:
            tenant_db.close()
    return total


@router.get("/service-catalog/offerings", response_model=list[OfferingView])
def list_offerings(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    del principal
    rows = service.list_offerings(db)
    db.commit()
    return rows


@router.get("/client-operations/overview")
def client_operations_overview(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.client_overview(db, principal.tenant_id)


@router.get("/client-operations/events")
def client_operations_events(
    request: Request,
    after_sequence: int = 0,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
):
    tenant_id = principal.tenant_id
    user_id = principal.user_id

    async def stream():
        sequence = max(0, after_sequence)
        if sequence == 0:
            initial_db = SessionLocal()
            try:
                set_tenant_context(initial_db, tenant_id, user_id)
                sequence = int(
                    initial_db.query(func.max(LedgerRecord.tenant_sequence))
                    .filter(LedgerRecord.tenant_id == tenant_id)
                    .scalar()
                    or 0
                )
            finally:
                initial_db.close()
        idle_ticks = 0
        while not await request.is_disconnected():
            event_db = SessionLocal()
            try:
                set_tenant_context(event_db, tenant_id, user_id)
                events = (
                    event_db.query(LedgerRecord)
                    .filter(LedgerRecord.tenant_id == tenant_id, LedgerRecord.tenant_sequence > sequence)
                    .order_by(LedgerRecord.tenant_sequence.asc())
                    .limit(100)
                    .all()
                )
                for event in events:
                    sequence = event.tenant_sequence
                    yield f"id: {sequence}\ndata: {json.dumps(model_to_dict(event), ensure_ascii=False)}\n\n"
                    idle_ticks = 0
            finally:
                event_db.close()
            idle_ticks += 1
            if idle_ticks >= 15:
                yield ": keep-alive\n\n"
                idle_ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/engagements")
def list_engagements(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.list_engagements(db, principal.tenant_id)


@router.post("/engagements")
def create_engagement(
    payload: EngagementCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "engagement.create", request_payload)
    if cached is not None:
        return cached
    engagement = service.create_engagement(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        correlation_id=_correlation_id(request), payload=request_payload,
        event_idempotency_key=f"engagement-created:{key}",
    )
    return _finish(db, receipt, model_to_dict(engagement), "engagement", engagement.id)


@router.get("/engagements/{engagement_id}")
def get_engagement(
    engagement_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.engagement_bundle(db, principal.tenant_id, engagement_id)


@router.post("/engagements/{engagement_id}/plans/generate")
def generate_engagement_plan(
    engagement_id: str,
    payload: PlanGenerateRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "engagement.generate_plan", {"engagement_id": engagement_id, **request_payload})
    if cached is not None:
        return cached
    plan = service.generate_plan(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, expected_version=payload.expected_version,
        adaptation_brief=payload.adaptation_brief, knowledge_base_ids=payload.knowledge_base_ids,
        correlation_id=_correlation_id(request), event_idempotency_key=f"engagement-plan-generated:{key}",
    )
    return _finish(db, receipt, model_to_dict(plan), "engagement_plan", plan.id)


@router.post("/engagements/{engagement_id}/plans/{plan_version}/approve")
def approve_engagement_plan(
    engagement_id: str,
    plan_version: int,
    payload: PlanApprovalRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "engagement.approve_plan", {"engagement_id": engagement_id, "plan_version": plan_version, **request_payload})
    if cached is not None:
        return cached
    plan = service.approve_plan(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, plan_version=plan_version, expected_version=payload.expected_version,
        comment=payload.comment, correlation_id=_correlation_id(request),
        event_idempotency_key=f"engagement-plan-approved:{key}",
    )
    return _finish(db, receipt, model_to_dict(plan), "engagement_plan", plan.id)


@router.post("/engagements/{engagement_id}/activate")
def activate_engagement(
    engagement_id: str,
    payload: EngagementActivationRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "engagement.activate", {"engagement_id": engagement_id, **request_payload})
    if cached is not None:
        return cached
    engagement = service.activate_engagement(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, expected_version=payload.expected_version, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"engagement-activated:{key}",
    )
    return _finish(db, receipt, model_to_dict(engagement), "engagement", engagement.id)


@router.get("/service-work-items")
def list_service_work_items(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.list_work_items(db, principal.tenant_id)


@router.post("/service-work-items/{item_id}/transitions")
def transition_service_work_item(
    item_id: str,
    payload: WorkItemTransitionRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_work_item.transition", {"item_id": item_id, **request_payload})
    if cached is not None:
        return cached
    item = service.transition_work_item(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, item_id=item_id,
        status=payload.status, expected_version=payload.expected_version, reason=payload.reason,
        override_reason=payload.override_reason, global_active=_global_active_wip(principal, db),
        correlation_id=_correlation_id(request), event_idempotency_key=f"service-work-transition:{key}",
    )
    return _finish(db, receipt, model_to_dict(item), "service_work_item", item.id)


@router.get("/service-deliverables")
def list_service_deliverables(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.list_deliverables(db, principal.tenant_id)


@router.get("/service-deliverables/{deliverable_id}")
def get_service_deliverable(
    deliverable_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.get_deliverable(db, principal.tenant_id, deliverable_id)


@router.post("/service-deliverables/{deliverable_id}/revisions")
def create_deliverable_revision(
    deliverable_id: str,
    payload: DeliverableRevisionCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_deliverable.create_revision", {"deliverable_id": deliverable_id, **request_payload})
    if cached is not None:
        return cached
    revision = service.create_revision(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, deliverable_id=deliverable_id,
        content=payload.content, artifact_refs=payload.artifact_refs, evidence_refs=payload.evidence_refs,
        model_call_id="", correlation_id=_correlation_id(request), event_idempotency_key=f"deliverable-revision:{key}",
    )
    return _finish(db, receipt, model_to_dict(revision), "deliverable_revision", revision.id)


@router.post("/service-deliverables/{deliverable_id}/revisions/generate")
def generate_deliverable_revision(
    deliverable_id: str,
    payload: DeliverableGenerateRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_deliverable.generate_revision", {"deliverable_id": deliverable_id, **request_payload})
    if cached is not None:
        return cached
    revision = service.generate_deliverable(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, deliverable_id=deliverable_id,
        instructions=payload.instructions, knowledge_base_ids=payload.knowledge_base_ids,
        correlation_id=_correlation_id(request), event_idempotency_key=f"deliverable-ai-revision:{key}",
    )
    return _finish(db, receipt, model_to_dict(revision), "deliverable_revision", revision.id)


@router.post("/service-deliverables/{deliverable_id}/submit")
def submit_service_deliverable(
    deliverable_id: str,
    payload: SubmitDeliverableRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_deliverable.submit", {"deliverable_id": deliverable_id, **request_payload})
    if cached is not None:
        return cached
    approval = service.submit_deliverable(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, deliverable_id=deliverable_id,
        expected_version=payload.expected_version, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"deliverable-submitted:{key}",
    )
    return _finish(db, receipt, model_to_dict(approval), "approval", approval.id)


@router.post("/service-deliverables/{deliverable_id}/decisions")
def decide_service_deliverable(
    deliverable_id: str,
    payload: DeliverableDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_deliverable.decide", {"deliverable_id": deliverable_id, **request_payload})
    if cached is not None:
        return cached
    deliverable = service.decide_deliverable(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, deliverable_id=deliverable_id,
        expected_version=payload.expected_version, decision=payload.decision, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"deliverable-decision:{key}",
    )
    return _finish(db, receipt, model_to_dict(deliverable), "service_deliverable", deliverable.id)


@router.post("/service-deliverables/{deliverable_id}/deliver")
def deliver_service_deliverable(
    deliverable_id: str,
    payload: DeliverableDeliveryRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_deliverable.deliver", {"deliverable_id": deliverable_id, **request_payload})
    if cached is not None:
        return cached
    deliverable = service.deliver_deliverable(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, deliverable_id=deliverable_id,
        expected_version=payload.expected_version, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"deliverable-delivered:{key}",
    )
    return _finish(db, receipt, model_to_dict(deliverable), "service_deliverable", deliverable.id)


@router.get("/outcome-metrics")
def list_outcome_metrics(
    engagement_id: str | None = None,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.list_outcomes(db, principal.tenant_id, engagement_id)


@router.post("/engagements/{engagement_id}/outcomes")
def create_outcome_metric(
    engagement_id: str,
    payload: OutcomeMetricCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "outcome_metric.create", {"engagement_id": engagement_id, **request_payload})
    if cached is not None:
        return cached
    metric = service.create_outcome(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, engagement_id=engagement_id,
        payload=payload.model_dump(), correlation_id=_correlation_id(request),
        event_idempotency_key=f"outcome-created:{key}",
    )
    return _finish(db, receipt, model_to_dict(metric), "outcome_metric", metric.id)


@router.post("/outcome-metrics/{metric_id}/observations")
def observe_outcome_metric(
    metric_id: str,
    payload: OutcomeObservationRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "outcome_metric.observe", {"metric_id": metric_id, **request_payload})
    if cached is not None:
        return cached
    metric = service.observe_outcome(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, metric_id=metric_id,
        payload=payload.model_dump(), correlation_id=_correlation_id(request),
        event_idempotency_key=f"outcome-observed:{key}",
    )
    return _finish(db, receipt, model_to_dict(metric), "outcome_metric", metric.id)


@router.get("/agent-catalog")
def get_agent_catalog(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    result = service.list_agent_catalog(db, principal.tenant_id)
    db.commit()
    return result


@router.get("/agent-gaps")
def list_agent_gaps(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    result = service.list_agent_catalog(db, principal.tenant_id)["gaps"]
    db.commit()
    return result


@router.post("/agent-gaps")
def create_agent_gap(
    payload: CapabilityGapCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "agent_gap.create", request_payload)
    if cached is not None:
        return cached
    gap = service.create_gap(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, payload=request_payload,
        correlation_id=_correlation_id(request), event_idempotency_key=f"agent-gap-created:{key}",
    )
    return _finish(db, receipt, model_to_dict(gap), "capability_gap", gap.id)


@router.post("/agent-gaps/{gap_id}/generate-candidate")
def generate_agent_candidate(
    gap_id: str,
    payload: AgentCandidateProposal,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    key, receipt, cached = _command(db, principal, request, "agent_candidate.generate", {"gap_id": gap_id, **payload.model_dump(mode="json")})
    if cached is not None:
        return cached
    candidate = service.generate_agent_candidate(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, gap_id=gap_id,
        constraints=payload.constraints, correlation_id=_correlation_id(request),
        event_idempotency_key=f"agent-candidate-generated:{key}",
    )
    return _finish(db, receipt, model_to_dict(candidate), "agent_candidate", candidate.id)


@router.get("/agent-candidates/{candidate_id}")
def get_agent_candidate(
    candidate_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.get_candidate(db, principal.tenant_id, candidate_id)


@router.post("/agent-candidates/{candidate_id}/evaluate")
def evaluate_agent_candidate(
    candidate_id: str,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    key, receipt, cached = _command(db, principal, request, "agent_candidate.evaluate", {"candidate_id": candidate_id})
    if cached is not None:
        return cached
    evaluation = service.evaluate_candidate(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, candidate_id=candidate_id,
        correlation_id=_correlation_id(request), event_idempotency_key=f"agent-candidate-evaluated:{key}",
    )
    return _finish(db, receipt, model_to_dict(evaluation), "agent_evaluation", evaluation.id)


@router.post("/agent-candidates/{candidate_id}/decisions")
def decide_agent_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "agent_candidate.decide", {"candidate_id": candidate_id, **request_payload})
    if cached is not None:
        return cached
    candidate = service.decide_candidate(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, candidate_id=candidate_id,
        decision=payload.decision, comment=payload.comment, correlation_id=_correlation_id(request),
        event_idempotency_key=f"agent-candidate-decision:{key}",
    )
    return _finish(db, receipt, model_to_dict(candidate), "agent_candidate", candidate.id)


@router.post("/agent-assignments")
def create_agent_assignment(
    payload: AgentAssignmentCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES, "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "agent_assignment.create", request_payload)
    if cached is not None:
        return cached
    assignment = service.create_assignment(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, payload=request_payload,
        correlation_id=_correlation_id(request), event_idempotency_key=f"agent-assignment-created:{key}",
    )
    return _finish(db, receipt, model_to_dict(assignment), "agent_assignment", assignment.id)
