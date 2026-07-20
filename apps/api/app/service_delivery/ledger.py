import hashlib
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.domain.ids import new_id
from app.models import AgentEvent, AuditLog, AuditProjection, GamificationEvent, LedgerHead, LedgerRecord


GAMIFICATION_POINTS = {
    "knowledge.document_indexed": 10,
    "ai.mvp.scoped": 20,
    "mvp_run.asf_run_created": 20,
    "quality.gate_passed": 10,
    "homologation.package_created": 50,
    "approval.approved": 20,
    "deliverable.approved_and_delivered": 100,
}


def _canonical(value: Dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_record(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _lock_tenant_ledger(db: Session, tenant_id: str) -> None:
    """Serialize a tenant hash chain for the duration of the transaction."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
            {"tenant_id": tenant_id},
        )


def _ledger_head(db: Session, tenant_id: str) -> LedgerHead:
    head = db.query(LedgerHead).filter_by(tenant_id=tenant_id).with_for_update().first()
    if head:
        return head
    previous = (
        db.query(LedgerRecord)
        .filter_by(tenant_id=tenant_id)
        .order_by(LedgerRecord.tenant_sequence.desc(), LedgerRecord.created_at.desc(), LedgerRecord.id.desc())
        .first()
    )
    head = LedgerHead(
        tenant_id=tenant_id,
        last_sequence=int(previous.tenant_sequence if previous else 0),
        last_hash=previous.integrity_hash if previous else "",
    )
    db.add(head)
    db.flush()
    return head


def append_ledger_event(
    db: Session,
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    actor_user_id: str = "",
    correlation_id: str = "",
    causation_id: str = "",
    idempotency_key: str = "",
    payload: Optional[Dict[str, Any]] = None,
    project_agent_event: bool = False,
) -> LedgerRecord:
    _lock_tenant_ledger(db, tenant_id)
    if idempotency_key:
        existing = db.query(LedgerRecord).filter_by(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
        if existing:
            if (
                existing.aggregate_type != aggregate_type
                or existing.aggregate_id != aggregate_id
                or existing.event_type != event_type
                or existing.payload_json != (payload or {})
            ):
                raise ValueError("Ledger idempotency key was reused with different event data")
            return existing
    head = _ledger_head(db, tenant_id)
    tenant_sequence = head.last_sequence + 1
    previous_hash = head.last_hash
    record_id = new_id()
    payload_json = payload or {}
    integrity_hash = _hash_record(
        {
            "id": record_id,
            "tenant_id": tenant_id,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
        }
    )
    record = LedgerRecord(
        id=record_id,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key=idempotency_key,
        tenant_sequence=tenant_sequence,
        payload_json=payload_json,
        previous_hash=previous_hash,
        integrity_hash=integrity_hash,
    )
    db.add(record)
    db.flush()
    head.last_sequence = tenant_sequence
    head.last_hash = integrity_hash
    _project_audit(db, record)
    _project_gamification(db, record)
    if project_agent_event:
        _project_agent_event(db, record)
    return record


def _project_audit(db: Session, record: LedgerRecord) -> None:
    summary = str(record.payload_json.get("summary") or record.event_type)
    projection = AuditProjection(
        id=new_id(),
        tenant_id=record.tenant_id,
        ledger_record_id=record.id,
        actor_user_id=record.actor_user_id,
        action=record.event_type,
        resource_type=record.aggregate_type,
        resource_id=record.aggregate_id,
        summary=summary,
        metadata_json=record.payload_json,
    )
    db.add(projection)
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=record.tenant_id,
            actor_user_id=record.actor_user_id,
            action=record.event_type,
            resource_type=record.aggregate_type,
            resource_id=record.aggregate_id,
            metadata_json=record.payload_json,
            ledger_record_id=record.id,
        )
    )
    db.flush()


def _project_agent_event(db: Session, record: LedgerRecord) -> None:
    payload = record.payload_json
    db.add(
        AgentEvent(
            id=new_id(),
            tenant_id=record.tenant_id,
            run_id=str(payload.get("run_id") or record.aggregate_id),
            node_id=str(payload.get("node_id") or ""),
            phase=str(payload.get("phase") or ""),
            agent_name=str(payload.get("agent_name") or ""),
            event_type=record.event_type,
            status=str(payload.get("status") or "success"),
            severity=str(payload.get("severity") or "info"),
            summary=str(payload.get("summary") or record.event_type),
            payload_json={**payload, "ledger_record_id": record.id},
            workflow_id=str(payload.get("workflow_id") or ""),
            activity_id=str(payload.get("activity_id") or ""),
            model_call_id=str(payload.get("model_call_id") or ""),
            tool_call_id=str(payload.get("tool_call_id") or ""),
        )
    )
    db.flush()


def _project_gamification(db: Session, record: LedgerRecord) -> None:
    points = GAMIFICATION_POINTS.get(record.event_type)
    if points is None:
        return
    beneficiary = record.actor_user_id or "tenant-team"
    existing = db.query(GamificationEvent).filter_by(
        tenant_id=record.tenant_id,
        ledger_record_id=record.id,
        event_type=record.event_type,
        user_or_team=beneficiary,
    ).first()
    if existing:
        return
    db.add(
        GamificationEvent(
            id=new_id(),
            tenant_id=record.tenant_id,
            user_or_team=beneficiary,
            event_type=record.event_type,
            points=points,
            reason=str(record.payload_json.get("summary") or record.event_type),
            ledger_record_id=record.id,
        )
    )
    db.flush()


def verify_hash_chain(db: Session, tenant_id: str) -> bool:
    previous_hash = ""
    rows = (
        db.query(LedgerRecord)
        .filter_by(tenant_id=tenant_id)
        .order_by(LedgerRecord.tenant_sequence.asc(), LedgerRecord.created_at.asc(), LedgerRecord.id.asc())
        .all()
    )
    expected_sequence = 1
    for row in rows:
        if row.tenant_sequence != expected_sequence:
            return False
        expected = _hash_record(
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "event_type": row.event_type,
                "actor_user_id": row.actor_user_id,
                "correlation_id": row.correlation_id,
                "causation_id": row.causation_id,
                "payload_json": row.payload_json,
                "previous_hash": previous_hash,
            }
        )
        if row.previous_hash != previous_hash or row.integrity_hash != expected:
            return False
        previous_hash = row.integrity_hash
        expected_sequence += 1
    return True


def rebuild_projections(db: Session, tenant_id: str) -> Dict[str, int]:
    """Rebuild disposable audit and agent-event read models from the ledger."""
    db.query(AuditLog).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(AuditProjection).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(AgentEvent).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(GamificationEvent).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    audit_count = 0
    agent_count = 0
    gamification_count = 0
    rows = (
        db.query(LedgerRecord)
        .filter_by(tenant_id=tenant_id)
        .order_by(LedgerRecord.tenant_sequence.asc())
        .all()
    )
    for record in rows:
        _project_audit(db, record)
        audit_count += 1
        if record.event_type in GAMIFICATION_POINTS:
            _project_gamification(db, record)
            gamification_count += 1
        if record.payload_json.get("run_id"):
            _project_agent_event(db, record)
            agent_count += 1
    db.flush()
    return {
        "audit_projections": audit_count,
        "agent_events": agent_count,
        "gamification_events": gamification_count,
    }
