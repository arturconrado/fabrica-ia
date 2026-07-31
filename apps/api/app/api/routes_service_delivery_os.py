import asyncio
import gzip
import json
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import SessionLocal, get_db, set_tenant_context
from app.models import LedgerHead, LedgerRecord, Membership, ServiceWorkItem
from app.schemas.service_delivery_os import (
    AcceptanceDecisionRequest,
    AcceptanceEvidenceRequest,
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
    OfferingVersionDecisionRequest,
    PlatformReadinessEvaluationRequest,
    PortfolioValidationEvidenceRequest,
    OfferingView,
    OutcomeMetricCreate,
    OutcomeObservationRequest,
    PlanApprovalRequest,
    PlanGenerateRequest,
    ServiceCycleCreate,
    ServiceExecutionCancelRequest,
    ServiceExecutionRequest,
    ServiceExecutionRetryRequest,
    WorkItemTransitionRequest,
)
from app.service_delivery.commands import begin_command, complete_command
from app.service_delivery.os_service import ServiceDeliveryOSService
from app.service_delivery.service import DomainError
from app.services.serialization import model_to_dict


router = APIRouter(prefix="/api/v1", tags=["service-delivery-os"])
OPERATIONAL_ROLES = ("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
READINESS_READ_ROLES = (*OPERATIONAL_ROLES, "release_validator")
ADMIN_ROLES = ("owner", "super_admin", "tenant_admin", "admin")
OWNER_ROLES = ("owner", "super_admin")
service = ServiceDeliveryOSService()
_projection_cache: dict[tuple[int, str, str], tuple[int, bytes, bytes]] = {}
_projection_locks: defaultdict[tuple[int, str, str], Lock] = defaultdict(Lock)


class SubmitDeliverableRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(default="", max_length=4_000)


def _tenant_projection(
    db: Session,
    *,
    tenant_id: str,
    projection: str,
    build,
    accepts_gzip: bool = False,
    state_version: int | None = None,
) -> Response:
    """Return a ledger-versioned JSON projection without serving stale state.

    Every relevant mutation appends to the tenant ledger in the same
    transaction. The ledger head therefore provides a cheap, cross-process
    invalidation version while each API worker keeps only serialized,
    tenant-scoped bytes in memory.
    """
    key = (id(db.get_bind()), tenant_id, projection)
    with _projection_locks[key]:
        if state_version is None:
            head = db.get(LedgerHead, tenant_id)
            state_version = int(head.last_sequence if head else 0)
        cached = _projection_cache.get(key)
        if cached and cached[0] == state_version:
            db.rollback()
            content = cached[2] if accepts_gzip else cached[1]
            headers = {
                "Cache-Control": "private, no-store",
                "X-ASF-Projection-Cache": "hit",
                "X-ASF-Projection-State": str(state_version),
                "Vary": "Accept-Encoding",
            }
            if accepts_gzip:
                headers["Content-Encoding"] = "gzip"
            return Response(
                content=content,
                media_type="application/json",
                headers=headers,
            )
        value = build()
        db.rollback()
        payload = json.dumps(
            jsonable_encoder(value),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        compressed = gzip.compress(payload, compresslevel=5)
        _projection_cache[key] = (state_version, payload, compressed)
        content = compressed if accepts_gzip else payload
        headers = {
            "Cache-Control": "private, no-store",
            "X-ASF-Projection-Cache": "miss",
            "X-ASF-Projection-State": str(state_version),
            "Vary": "Accept-Encoding",
        }
        if accepts_gzip:
            headers["Content-Encoding"] = "gzip"
        return Response(
            content=content,
            media_type="application/json",
            headers=headers,
        )


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
    try:
        for membership in memberships:
            if membership.role not in OPERATIONAL_ROLES:
                continue
            set_tenant_context(db, membership.tenant_id, principal.user_id)
            total += db.query(ServiceWorkItem).filter_by(
                tenant_id=membership.tenant_id, status="in_progress"
            ).count()
    finally:
        set_tenant_context(db, principal.tenant_id, principal.user_id)
    return total


def _portfolio_readiness_for_principal(
    principal: Principal, db: Session, version_label: str
) -> dict[str, Any]:
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .execution_options(include_all_tenants=True)
        .all()
    )
    tenant_ids = {principal.tenant_id}
    tenant_ids.update(
        membership.tenant_id
        for membership in memberships
        if membership.role in OPERATIONAL_ROLES
    )
    results: list[dict[str, Any]] = []
    try:
        for tenant_id in sorted(tenant_ids):
            set_tenant_context(db, tenant_id, principal.user_id)
            results.append(service.portfolio_release_readiness(db, tenant_id, version_label))
    finally:
        set_tenant_context(db, principal.tenant_id, principal.user_id)
    return service.combine_portfolio_release_readiness(results, version_label)


@router.get("/service-catalog/offerings", response_model=list[OfferingView])
def list_offerings(
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return _tenant_projection(
        db,
        tenant_id=principal.tenant_id,
        projection="service-catalog",
        build=lambda: service.list_offerings(db),
        accepts_gzip="gzip" in request.headers.get("Accept-Encoding", "").casefold(),
    )


@router.get("/service-catalog/versions/{version_label}/readiness")
def portfolio_version_readiness(
    version_label: str,
    principal: Principal = Depends(require_roles(*READINESS_READ_ROLES)),
    db: Session = Depends(get_db),
):
    return _portfolio_readiness_for_principal(principal, db, version_label)


@router.post("/service-catalog/versions/{version_label}/decision")
def decide_portfolio_version(
    version_label: str,
    payload: OfferingVersionDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(
        db, principal, request, "service_portfolio.decide", {"version": version_label, **request_payload}
    )
    if cached is not None:
        return cached
    readiness = _portfolio_readiness_for_principal(principal, db, version_label)
    result = service.decide_portfolio_version(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        version_label=version_label, decision=payload.decision, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"service-portfolio-decision:{key}",
        readiness=readiness,
    )
    return _finish(db, receipt, result, "service_portfolio", f"portfolio:{version_label}")


@router.post("/service-catalog/versions/{version_label}/evidence")
def record_portfolio_validation_evidence(
    version_label: str,
    payload: PortfolioValidationEvidenceRequest,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin", "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(
        db, principal, request, "service_portfolio.record_validation",
        {"version": version_label, **request_payload},
    )
    if cached is not None:
        return cached
    artifact = service.record_portfolio_validation_evidence(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        actor_role=principal.role, version_label=version_label,
        report_kind=payload.report_kind, status=payload.status,
        content_markdown=payload.content_markdown, evidence_refs=payload.evidence_refs,
        metrics=payload.metrics, manifest=payload.manifest.model_dump(mode="json") if payload.manifest else None,
        correlation_id=_correlation_id(request),
        event_idempotency_key=f"service-portfolio-evidence:{key}",
    )
    return _finish(db, receipt, model_to_dict(artifact), "artifact", artifact.id)


@router.post("/admin/platform-readiness/evaluations")
def create_platform_readiness_evaluation(
    payload: PlatformReadinessEvaluationRequest,
    request: Request,
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(
        db, principal, request, "platform_readiness.evaluate", request_payload,
    )
    if cached is not None:
        return cached
    readiness = _portfolio_readiness_for_principal(principal, db, payload.portfolio_version)
    evaluation = service.create_platform_readiness_evaluation(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        evaluation_type=payload.evaluation_type, version_label=payload.portfolio_version,
        comment=payload.comment, readiness=readiness, correlation_id=_correlation_id(request),
        event_idempotency_key=f"platform-readiness-evaluation:{key}",
    )
    return _finish(db, receipt, model_to_dict(evaluation), "platform_readiness", evaluation.id)


@router.get("/client-operations/overview")
def client_operations_overview(
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return _tenant_projection(
        db,
        tenant_id=principal.tenant_id,
        projection="client-operations-overview",
        build=lambda: service.client_overview(db, principal.tenant_id),
        accepts_gzip="gzip" in request.headers.get("Accept-Encoding", "").casefold(),
    )


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
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return _tenant_projection(
        db,
        tenant_id=principal.tenant_id,
        projection="engagements",
        build=lambda: service.list_engagements(db, principal.tenant_id),
        accepts_gzip="gzip" in request.headers.get("Accept-Encoding", "").casefold(),
    )


@router.post("/engagements")
def create_engagement(
    payload: EngagementCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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


@router.get("/engagements/{engagement_id}/package/download")
def download_engagement_package(
    engagement_id: str,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    filename, payload, manifest = service.build_engagement_package(
        db,
        principal.tenant_id,
        engagement_id,
        actor_user_id=principal.user_id,
        correlation_id=_correlation_id(request),
    )
    db.commit()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Package-SHA256": str(manifest["package_sha256"]),
            "X-Package-Size": str(manifest["package_size_bytes"]),
        },
    )


@router.post("/engagements/{engagement_id}/plans/generate")
def generate_engagement_plan(
    engagement_id: str,
    payload: PlanGenerateRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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
    principal: Principal = Depends(require_roles("engagement_manager")),
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
        event_idempotency_key=f"engagement-plan-approved:{key}", validation_mode=payload.validation_mode,
    )
    return _finish(db, receipt, model_to_dict(plan), "engagement_plan", plan.id)


@router.post("/engagements/{engagement_id}/activate")
def activate_engagement(
    engagement_id: str,
    payload: EngagementActivationRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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


@router.post("/engagements/{engagement_id}/cycles")
def create_service_cycle(
    engagement_id: str,
    payload: ServiceCycleCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_cycle.create", {"engagement_id": engagement_id, **request_payload})
    if cached is not None:
        return cached
    cycle = service.create_cycle(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, expected_version=payload.expected_version,
        period_start=payload.period_start, period_end=payload.period_end, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"service-cycle-created:{key}",
    )
    return _finish(db, receipt, model_to_dict(cycle), "service_cycle", cycle.id)


@router.get("/engagements/{engagement_id}/acceptance-checks")
def list_service_acceptance_checks(
    engagement_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.list_acceptance_checks(db, principal.tenant_id, engagement_id)


@router.post("/engagements/{engagement_id}/acceptance-checks/{check_id}/evidence")
def record_service_acceptance_evidence(
    engagement_id: str,
    check_id: str,
    payload: AcceptanceEvidenceRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_acceptance.evidence", {"engagement_id": engagement_id, "check_id": check_id, **request_payload})
    if cached is not None:
        return cached
    check = service.record_acceptance_evidence(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, check_id=check_id, expected_version=payload.expected_version,
        evidence_refs=payload.evidence_refs, external_constraint=payload.external_constraint,
        impact=payload.impact, mitigation=payload.mitigation,
        correlation_id=_correlation_id(request), event_idempotency_key=f"acceptance-evidence:{key}",
    )
    return _finish(db, receipt, model_to_dict(check), "service_acceptance_check", check.id)


@router.post("/engagements/{engagement_id}/acceptance-checks/{check_id}/decision")
def decide_service_acceptance_check(
    engagement_id: str,
    check_id: str,
    payload: AcceptanceDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_roles("engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_acceptance.decide", {"engagement_id": engagement_id, "check_id": check_id, **request_payload})
    if cached is not None:
        return cached
    check = service.decide_acceptance_check(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        engagement_id=engagement_id, check_id=check_id, expected_version=payload.expected_version,
        decision=payload.decision, comment=payload.comment,
        correlation_id=_correlation_id(request), event_idempotency_key=f"acceptance-decision:{key}",
        validation_mode=payload.validation_mode,
    )
    return _finish(db, receipt, model_to_dict(check), "service_acceptance_check", check.id)


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
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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


@router.post("/service-work-items/{item_id}/execute")
def execute_service_work_item(
    item_id: str,
    payload: ServiceExecutionRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_execution.queue", {"item_id": item_id, **request_payload})
    if cached is not None:
        return cached
    execution = service.queue_execution(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        item_id=item_id, expected_version=payload.expected_version, instructions=payload.instructions,
        knowledge_base_ids=payload.knowledge_base_ids, correlation_id=_correlation_id(request),
        event_idempotency_key=f"service-execution-queued:{key}",
    )
    return _finish(db, receipt, model_to_dict(execution), "service_execution", execution.id)


@router.get("/service-executions")
def list_service_executions(
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    rows = service.list_executions(db, principal.tenant_id)
    db.rollback()
    return rows


@router.get("/service-executions/{execution_id}")
def get_service_execution(
    execution_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.get_execution(db, principal.tenant_id, execution_id)


@router.post("/service-executions/{execution_id}/retry")
def retry_service_execution(
    execution_id: str,
    payload: ServiceExecutionRetryRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_execution.retry", {"execution_id": execution_id, **request_payload})
    if cached is not None:
        return cached
    execution = service.retry_execution(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        execution_id=execution_id, expected_version=payload.expected_version, reason=payload.reason,
        correlation_id=_correlation_id(request), event_idempotency_key=f"service-execution-retry:{key}",
    )
    return _finish(db, receipt, model_to_dict(execution), "service_execution", execution.id)


@router.post("/service-executions/{execution_id}/cancel")
def cancel_service_execution(
    execution_id: str,
    payload: ServiceExecutionCancelRequest,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump(mode="json")
    key, receipt, cached = _command(db, principal, request, "service_execution.cancel", {"execution_id": execution_id, **request_payload})
    if cached is not None:
        return cached
    execution = service.cancel_execution(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        execution_id=execution_id, expected_version=payload.expected_version, reason=payload.reason,
        correlation_id=_correlation_id(request), event_idempotency_key=f"service-execution-cancel:{key}",
    )
    return _finish(db, receipt, model_to_dict(execution), "service_execution", execution.id)


@router.get("/service-deliverables")
def list_service_deliverables(
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return _tenant_projection(
        db,
        tenant_id=principal.tenant_id,
        projection="service-deliverables",
        build=lambda: service.list_deliverables(db, principal.tenant_id),
        accepts_gzip="gzip" in request.headers.get("Accept-Encoding", "").casefold(),
    )


@router.get("/service-deliverables/{deliverable_id}")
def get_service_deliverable(
    deliverable_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    return service.get_deliverable(db, principal.tenant_id, deliverable_id)


@router.get("/service-deliverables/{deliverable_id}/package/download")
def download_service_deliverable_package(
    deliverable_id: str,
    request: Request,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    filename, payload, manifest = service.build_deliverable_package(
        db, principal.tenant_id, deliverable_id, actor_user_id=principal.user_id,
        correlation_id=_correlation_id(request),
    )
    db.commit()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Package-SHA256": str(manifest["package_sha256"]),
            "X-Package-Size": str(manifest["package_size_bytes"]),
        },
    )


@router.post("/service-deliverables/{deliverable_id}/revisions")
def create_deliverable_revision(
    deliverable_id: str,
    payload: DeliverableRevisionCreate,
    request: Request,
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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
    principal: Principal = Depends(require_roles(*OWNER_ROLES)),
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
    principal: Principal = Depends(require_roles("engagement_manager")),
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
        validation_mode=payload.validation_mode,
    )
    return _finish(db, receipt, model_to_dict(deliverable), "service_deliverable", deliverable.id)


@router.post("/service-deliverables/{deliverable_id}/deliver")
def deliver_service_deliverable(
    deliverable_id: str,
    payload: DeliverableDeliveryRequest,
    request: Request,
    principal: Principal = Depends(require_roles("engagement_manager")),
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
        validation_mode=payload.validation_mode,
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
