from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ComponentInstance, Entitlement, MvpRun, WorkflowRun, WorkflowSlot, utcnow
from app.service_delivery.service import DomainError


def contracted_workflow_limit(db: Session, run_id: str) -> Optional[int]:
    mvp_run = db.query(MvpRun).filter_by(workflow_run_id=run_id).first()
    if not mvp_run or not mvp_run.component_instance_id:
        return None
    component = db.query(ComponentInstance).filter_by(id=mvp_run.component_instance_id).first()
    if not component or not component.entitlement_id:
        return None
    entitlement = db.query(Entitlement).filter_by(id=component.entitlement_id, status="granted").first()
    if not entitlement:
        return None
    value = int((entitlement.limits_json or {}).get("concurrent_workflows") or 0)
    return value or None


def acquire_workflow_slot(db: Session, run_id: str, *, tenant_limit: Optional[int] = None) -> WorkflowSlot:
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise DomainError(404, "WORKFLOW_RUN_NOT_FOUND", "Workflow run does not exist")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('asf-global-workflow-capacity', 2))"))
    now = utcnow()
    existing = db.get(WorkflowSlot, run_id)
    if existing and (not existing.lease_expires_at or existing.lease_expires_at >= now):
        return existing
    if existing:
        db.delete(existing)
        db.flush()
    db.query(WorkflowSlot).filter(
        WorkflowSlot.lease_expires_at.is_not(None),
        WorkflowSlot.lease_expires_at < now,
    ).delete(synchronize_session=False)
    settings = get_settings()
    tenant_used = (
        db.query(WorkflowSlot)
        .join(WorkflowRun, WorkflowRun.id == WorkflowSlot.run_id)
        .filter(WorkflowRun.tenant_id == run.tenant_id)
        .count()
    )
    contracted_limit = tenant_limit or contracted_workflow_limit(db, run_id)
    effective_tenant_limit = settings.pilot_max_concurrent_workflows_per_tenant
    if contracted_limit:
        effective_tenant_limit = min(effective_tenant_limit, contracted_limit)
    if tenant_used >= effective_tenant_limit:
        raise DomainError(
            429,
            "TENANT_WORKFLOW_LIMIT",
            "Per-tenant pilot workflow capacity is exhausted",
            {"limit": effective_tenant_limit},
        )
    limit = settings.pilot_max_concurrent_workflows
    used = {slot.slot_number for slot in db.query(WorkflowSlot).with_for_update().all()}
    available = next((number for number in range(1, limit + 1) if number not in used), None)
    if available is None:
        raise DomainError(429, "PILOT_WORKFLOW_LIMIT", "Global pilot workflow capacity is exhausted")
    slot = WorkflowSlot(
        run_id=run_id,
        slot_number=available,
        acquired_at=now,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(minutes=10),
    )
    db.add(slot)
    db.flush()
    return slot


def release_workflow_slot(db: Session, run_id: str) -> None:
    db.query(WorkflowSlot).filter_by(run_id=run_id).delete(synchronize_session=False)


def heartbeat_workflow_slot(db: Session, run_id: str) -> bool:
    now = utcnow()
    updated = db.query(WorkflowSlot).filter_by(run_id=run_id).update(
        {"heartbeat_at": now, "lease_expires_at": now + timedelta(minutes=10)},
        synchronize_session=False,
    )
    return bool(updated)
