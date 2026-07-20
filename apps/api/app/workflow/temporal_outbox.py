import asyncio
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, set_tenant_context
from app.events.event_service import emit_event
from app.models import AgentRunState, TemporalCommandOutbox, WorkflowRun, WorkflowSlot, utcnow
from app.providers.temporal_runner import TemporalWorkflowRunner


COMMAND_LEASE = timedelta(minutes=2)
MAX_RETRY_DELAY_SECONDS = 300


class CancellationAwaitingProvider(RuntimeError):
    pass


def enqueue_temporal_command(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    command_type: str,
    workflow_id: str,
    deduplication_key: str,
    signal_name: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> TemporalCommandOutbox:
    existing = db.query(TemporalCommandOutbox).filter_by(deduplication_key=deduplication_key).first()
    if existing:
        if existing.tenant_id != tenant_id or existing.run_id != run_id or existing.command_type != command_type:
            raise ValueError("Temporal command deduplication key belongs to a different command")
        return existing
    safe_payload = payload or {}
    if command_type == "signal":
        # The outbox is a global orchestration table without RLS. Keep only
        # non-customer control codes; comments stay in tenant-scoped records.
        safe_payload = {key: safe_payload[key] for key in ("decision", "action") if key in safe_payload}
    command = TemporalCommandOutbox(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        run_id=run_id,
        command_type=command_type,
        workflow_id=workflow_id,
        signal_name=signal_name,
        payload_json=safe_payload,
        deduplication_key=deduplication_key,
        status="pending",
        next_attempt_at=utcnow(),
    )
    db.add(command)
    db.flush()
    return command


def enqueue_start(db: Session, run: WorkflowRun) -> TemporalCommandOutbox:
    workflow_id = run.temporal_workflow_id or TemporalWorkflowRunner.workflow_id(run.tenant_id, run.id)
    run.temporal_workflow_id = workflow_id
    return enqueue_temporal_command(
        db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        command_type="start",
        workflow_id=workflow_id,
        deduplication_key=f"temporal:start:{run.id}",
    )


def enqueue_signal(
    db: Session,
    run: WorkflowRun,
    *,
    signal_name: str,
    payload: Dict[str, Any],
    decision_key: str,
) -> TemporalCommandOutbox:
    return enqueue_temporal_command(
        db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        command_type="signal",
        workflow_id=run.temporal_workflow_id,
        signal_name=signal_name,
        payload=payload,
        deduplication_key=f"temporal:signal:{run.id}:{decision_key}",
    )


def enqueue_cancel(db: Session, run: WorkflowRun) -> TemporalCommandOutbox:
    return enqueue_temporal_command(
        db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        command_type="cancel",
        workflow_id=run.temporal_workflow_id,
        deduplication_key=f"temporal:cancel:{run.id}",
    )


def _claim_next_command() -> Optional[Dict[str, str]]:
    db = SessionLocal()
    try:
        now = utcnow()
        query = (
            db.query(TemporalCommandOutbox)
            .filter(
                or_(
                    TemporalCommandOutbox.status == "pending",
                    (TemporalCommandOutbox.status == "processing")
                    & (TemporalCommandOutbox.lease_expires_at < now),
                ),
                or_(TemporalCommandOutbox.next_attempt_at.is_(None), TemporalCommandOutbox.next_attempt_at <= now),
            )
            .order_by(TemporalCommandOutbox.created_at, TemporalCommandOutbox.id)
        )
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        command = query.first()
        if not command:
            db.rollback()
            return None
        command.status = "processing"
        command.attempt_count += 1
        command.lease_expires_at = now + COMMAND_LEASE
        command.updated_at = now
        result = {"id": command.id, "tenant_id": command.tenant_id}
        db.commit()
        return result
    finally:
        db.close()


async def dispatch_one_temporal_command() -> bool:
    claimed = _claim_next_command()
    if not claimed:
        return False
    db = SessionLocal()
    try:
        set_tenant_context(db, claimed["tenant_id"])
        command = db.query(TemporalCommandOutbox).filter_by(id=claimed["id"]).first()
        if not command:
            return True
        run = db.query(WorkflowRun).filter_by(id=command.run_id, tenant_id=command.tenant_id).first()
        if not run:
            raise RuntimeError(f"Temporal outbox run not found: {command.run_id}")
        runner = TemporalWorkflowRunner()
        reconciled = False
        if command.command_type == "start":
            result = await runner.start_enterprise_run(
                tenant_id=run.tenant_id,
                demand=run.demand,
                project_id=run.project_id,
                run_id=run.id,
                executor_protocol_version=run.executor_protocol_version,
            )
            run.temporal_workflow_id = result.workflow_id
            run.temporal_run_id = result.run_id
            if run.status == "temporal_dispatch_pending":
                run.status = result.status
            run.current_phase = "temporal_scheduled"
        elif command.command_type == "signal":
            if await runner.is_workflow_closed(command.workflow_id):
                reconciled = True
            else:
                try:
                    await runner.signal(command.workflow_id, command.signal_name, command.payload_json or {})
                except Exception:
                    if not await runner.is_workflow_closed(command.workflow_id):
                        raise
                    reconciled = True
        elif command.command_type == "cancel":
            if not await runner.is_workflow_closed(command.workflow_id):
                try:
                    await runner.cancel(command.workflow_id)
                except Exception:
                    if not await runner.is_workflow_closed(command.workflow_id):
                        raise
                    reconciled = True
            else:
                reconciled = True
            db.refresh(run)
            if run.status == "cancel_requested":
                control = db.query(AgentRunState).filter_by(
                    run_id=run.id, tenant_id=run.tenant_id, agent_name="RUN_CONTROL"
                ).first()
                slot = db.get(WorkflowSlot, run.id)
                activity_active = bool(control and "temporal_activity_active" in (control.outputs_json or []))
                live_lease = bool(slot and slot.lease_expires_at and slot.lease_expires_at >= utcnow())
                if activity_active and live_lease:
                    raise CancellationAwaitingProvider("Temporal is closed; waiting for the provider thread to acknowledge cancellation")
                from app.services.run_service import provider

                provider._finalize_cancellation(db, run, commit=False)
        else:
            raise RuntimeError(f"Unsupported Temporal outbox command: {command.command_type}")

        command.status = "completed"
        command.completed_at = utcnow()
        command.lease_expires_at = None
        command.last_error = ""
        emit_event(
            db,
            run.id,
            "temporal.command_dispatched",
            f"Temporal command {command.command_type} dispatched.",
            payload={
                "command_id": command.id,
                "command_type": command.command_type,
                "attempt": command.attempt_count,
                "reconciled_terminal_workflow": reconciled,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        set_tenant_context(db, claimed["tenant_id"])
        command = db.query(TemporalCommandOutbox).filter_by(id=claimed["id"]).first()
        if command:
            delay = min(2 ** min(command.attempt_count, 8), MAX_RETRY_DELAY_SECONDS)
            command.status = "pending"
            command.next_attempt_at = utcnow() + timedelta(seconds=delay)
            command.lease_expires_at = None
            command.last_error = str(exc)[:4000]
            run = db.query(WorkflowRun).filter_by(id=command.run_id, tenant_id=command.tenant_id).first()
            if run and not isinstance(exc, CancellationAwaitingProvider):
                emit_event(
                    db,
                    run.id,
                    "temporal.command_retry_scheduled",
                    f"Temporal command {command.command_type} failed and will be retried.",
                    status="pending",
                    severity="warning",
                    payload={"command_id": command.id, "attempt": command.attempt_count, "error": str(exc)[:500]},
                )
            db.commit()
        return True
    finally:
        db.close()
    return True


async def run_temporal_outbox_dispatcher(poll_interval_seconds: float = 1.0) -> None:
    while True:
        dispatched = await dispatch_one_temporal_command()
        if not dispatched:
            await asyncio.sleep(poll_interval_seconds)
