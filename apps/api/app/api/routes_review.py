from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    Approval,
    ApprovalRequest,
    Artifact,
    HomologationPackage,
    HomologationReport,
    LedgerRecord,
    QualityGate,
    RequirementTrace,
    WorkflowRun,
    utcnow,
)
from app.schemas.operational import (
    ReviewArtifact,
    ReviewDecision,
    ReviewInboxResponse,
    ReviewItemResponse,
    ReviewPackage,
)
from app.service_delivery.ledger import append_ledger_event
from app.service_delivery.service import ServiceDeliveryService
from app.services.run_service import provider
from app.services.serialization import model_to_dict
from app.workflow.temporal_outbox import enqueue_signal


REVIEW_READ_ROLES = (
    "owner",
    "super_admin",
    "tenant_admin",
    "engagement_manager",
    "consultant",
    "admin",
    "operator",
    "client_sponsor",
    "process_owner",
    "reviewer",
    "auditor",
)
REVIEW_DECISION_ROLES = tuple(role for role in REVIEW_READ_ROLES if role != "auditor")
router = APIRouter(prefix="/api/v1/review", tags=["review"])
service = ServiceDeliveryService()


def _principal_dependency():
    return require_roles(*REVIEW_READ_ROLES)


def _selected(row, fields: tuple[str, ...]) -> dict:
    values = model_to_dict(row)
    return {field: values.get(field) for field in fields}


def _safe_artifact(row: Artifact) -> dict:
    return _selected(
        row,
        ("id", "run_id", "name", "artifact_type", "content", "audience", "evidence_classification", "created_at"),
    )


def _safe_package(row: HomologationPackage) -> dict:
    manifest = row.manifest_json or {}
    artifacts = [
        {key: item.get(key) for key in ("id", "name", "classification")}
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
    ]
    safe_manifest = {
        key: manifest.get(key)
        for key in ("run_id", "project_id", "generated_at", "status", "hrs", "tests", "gates", "blockers", "evidence_policy", "risks")
        if key in manifest
    }
    safe_manifest["artifacts"] = artifacts
    values = _selected(row, ("id", "run_id", "status", "created_at"))
    values["manifest_json"] = safe_manifest
    return values


def _run_bundle(db: Session, tenant_id: str, run: WorkflowRun) -> dict:
    gates = db.query(QualityGate).filter_by(tenant_id=tenant_id, run_id=run.id).order_by(QualityGate.created_at.asc()).all()
    traces = db.query(RequirementTrace).filter_by(tenant_id=tenant_id, run_id=run.id).order_by(RequirementTrace.requirement_id.asc()).all()
    artifacts = (
        db.query(Artifact)
        .filter(Artifact.tenant_id == tenant_id, Artifact.run_id == run.id, Artifact.audience.in_(["reviewer", "client"]))
        .order_by(Artifact.created_at.asc())
        .all()
    )
    packages = db.query(HomologationPackage).filter_by(tenant_id=tenant_id, run_id=run.id).order_by(HomologationPackage.created_at.desc()).all()
    reports = db.query(HomologationReport).filter_by(tenant_id=tenant_id, run_id=run.id).order_by(HomologationReport.created_at.desc()).all()
    return {
        "run": _selected(
            run,
            ("id", "project_id", "status", "current_phase", "current_node", "homologation_readiness_score", "started_at", "finished_at"),
        ),
        "quality_gates": [
            _selected(row, ("id", "gate_id", "name", "category", "status", "score", "blockers_json", "warnings_json", "evidence_json", "created_at"))
            for row in gates
        ],
        "traceability": [
            _selected(row, ("id", "requirement_id", "file_path", "test_name", "evidence", "status", "created_at"))
            for row in traces
        ],
        "artifacts": [_safe_artifact(row) for row in artifacts],
        "packages": [_safe_package(row) for row in packages],
        "reports": [
            _selected(row, ("id", "run_id", "status", "score", "blockers_json", "risks_json", "summary", "created_at"))
            for row in reports
        ],
    }


def _inbox_item(kind: str, approval) -> dict:
    if kind == "run":
        return {
            "id": approval.id,
            "kind": kind,
            "title": approval.title,
            "description": approval.description,
            "status": approval.status,
            "risk_level": approval.risk_level,
            "run_id": approval.run_id,
            "created_at": approval.created_at.isoformat(),
            "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
        }
    return {
        "id": approval.id,
        "kind": kind,
        "title": approval.title,
        "description": approval.description,
        "status": approval.status,
        "risk_level": str((approval.impact_json or {}).get("risk_level") or "medium"),
        "resource_type": approval.resource_type,
        "resource_id": approval.resource_id,
        "created_at": approval.created_at.isoformat(),
        "resolved_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


@router.get("/inbox", response_model=ReviewInboxResponse)
def review_inbox(principal: Principal = Depends(_principal_dependency()), db: Session = Depends(get_db)):
    run_approvals = db.query(ApprovalRequest).filter_by(tenant_id=principal.tenant_id).order_by(ApprovalRequest.created_at.desc()).all()
    service_approvals = db.query(Approval).filter_by(tenant_id=principal.tenant_id).order_by(Approval.created_at.desc()).all()
    items = [_inbox_item("run", row) for row in run_approvals] + [_inbox_item("service", row) for row in service_approvals]
    items.sort(key=lambda item: (item["status"] != "pending", item["created_at"]), reverse=False)
    return {"tenant_id": principal.tenant_id, "items": items}


@router.get("/evidence", response_model=list[ReviewArtifact])
def review_evidence(principal: Principal = Depends(_principal_dependency()), db: Session = Depends(get_db)):
    rows = (
        db.query(Artifact)
        .filter(Artifact.tenant_id == principal.tenant_id, Artifact.audience.in_(["reviewer", "client"]))
        .order_by(Artifact.created_at.desc())
        .all()
    )
    return [_safe_artifact(row) for row in rows]


@router.get("/deliverables", response_model=list[ReviewPackage])
def review_deliverables(principal: Principal = Depends(_principal_dependency()), db: Session = Depends(get_db)):
    rows = (
        db.query(HomologationPackage)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(HomologationPackage.created_at.desc())
        .all()
    )
    return [_safe_package(row) for row in rows]


@router.get("/items/{approval_id}", response_model=ReviewItemResponse)
def review_item(approval_id: str, principal: Principal = Depends(_principal_dependency()), db: Session = Depends(get_db)):
    run_approval = db.query(ApprovalRequest).filter_by(tenant_id=principal.tenant_id, id=approval_id).first()
    if run_approval:
        run = db.query(WorkflowRun).filter_by(tenant_id=principal.tenant_id, id=run_approval.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"approval": _inbox_item("run", run_approval), "review": _run_bundle(db, principal.tenant_id, run)}
    service_approval = db.query(Approval).filter_by(tenant_id=principal.tenant_id, id=approval_id).first()
    if service_approval:
        return {"approval": _inbox_item("service", service_approval), "review": None}
    raise HTTPException(status_code=404, detail="Review item not found")


@router.post("/items/{approval_id}/decisions", response_model=ReviewItemResponse)
def decide_review_item(
    approval_id: str,
    payload: ReviewDecision,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*REVIEW_DECISION_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.decision in {"reject", "changes_requested"} and not payload.comment.strip():
        raise HTTPException(status_code=422, detail="A comment is required for rejection or requested changes")
    existing = db.query(LedgerRecord).filter_by(tenant_id=principal.tenant_id, idempotency_key=idempotency_key).first()
    if existing:
        if existing.aggregate_id != approval_id:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for another review item")
        return review_item(approval_id, principal, db)

    service_approval = db.query(Approval).filter_by(tenant_id=principal.tenant_id, id=approval_id).first()
    if service_approval:
        if payload.decision == "changes_requested":
            service_approval.status = "pending"
            service_approval.decision = "changes_requested"
            service_approval.comments = payload.comment.strip()
            append_ledger_event(
                db,
                tenant_id=principal.tenant_id,
                aggregate_type="approval",
                aggregate_id=service_approval.id,
                event_type="approval.changes_requested",
                actor_user_id=principal.user_id,
                idempotency_key=idempotency_key,
                payload={"summary": f"Changes requested: {service_approval.title}", "comment": payload.comment.strip()},
            )
        else:
            service.decide_approval(
                db,
                principal.tenant_id,
                principal.user_id,
                idempotency_key,
                approval_id,
                payload.decision,
                payload.comment.strip(),
                idempotency_key,
            )
        db.commit()
        return review_item(approval_id, principal, db)

    run_approval = db.query(ApprovalRequest).filter_by(tenant_id=principal.tenant_id, id=approval_id).first()
    if not run_approval:
        raise HTTPException(status_code=404, detail="Review item not found")
    run = db.query(WorkflowRun).filter_by(tenant_id=principal.tenant_id, id=run_approval.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if payload.decision == "approve":
        run = provider.approve_run(db, run.id, payload.comment.strip(), commit=False)
        if get_settings().workflow_backend.lower() == "temporal" and run.temporal_workflow_id:
            enqueue_signal(db, run, signal_name="human_decision", payload={"decision": "approved"}, decision_key="approved")
    elif payload.decision == "reject":
        run = provider.reject_run(db, run.id, payload.comment.strip(), commit=False)
        if get_settings().workflow_backend.lower() == "temporal" and run.temporal_workflow_id:
            enqueue_signal(db, run, signal_name="human_decision", payload={"decision": "rejected"}, decision_key="rejected")
    else:
        run = provider.request_changes(db, run.id, payload.comment.strip(), commit=False)
        if get_settings().workflow_backend.lower() == "temporal" and run.temporal_workflow_id:
            enqueue_signal(
                db,
                run,
                signal_name="human_decision",
                payload={"decision": "changes_requested", "comment": payload.comment.strip()},
                decision_key=f"changes_requested:{idempotency_key}",
            )

    append_ledger_event(
        db,
        tenant_id=principal.tenant_id,
        aggregate_type="approval_request",
        aggregate_id=run_approval.id,
        event_type=f"review.{payload.decision}",
        actor_user_id=principal.user_id,
        idempotency_key=idempotency_key,
        payload={"summary": f"Review decision: {payload.decision}", "run_id": run.id, "comment": payload.comment.strip()},
    )
    db.commit()
    if (
        payload.decision == "changes_requested"
        and get_settings().workflow_backend.lower() != "temporal"
        and hasattr(provider, "resume_ai_native_rework")
    ):
        provider.resume_ai_native_rework(run.id, run.tenant_id)
    return review_item(approval_id, principal, db)
