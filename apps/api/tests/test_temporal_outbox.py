import asyncio
import uuid

import pytest

from app.db.session import SessionLocal, engine
from app.models import AgentRunState, Base, Project, TemporalCommandOutbox, Tenant, WorkflowRun, WorkflowSlot
from app.providers.temporal_runner import TemporalStartResult, TemporalWorkflowRunner
from app.workflow.temporal_outbox import dispatch_one_temporal_command, enqueue_cancel, enqueue_signal, enqueue_start


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _run(db, tenant_id: str = "outbox-tenant") -> WorkflowRun:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        tenant = Tenant(id=tenant_id, name="Outbox Tenant", slug=tenant_id)
        db.add(tenant)
    project = Project(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Outbox Project")
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="ContractFlow reference",
        status="temporal_dispatch_pending",
    )
    db.add_all([project, run])
    db.flush()
    db.add(WorkflowSlot(run_id=run.id, slot_number=1))
    enqueue_start(db, run)
    db.commit()
    return run


def test_start_command_is_transactional_and_deduplicated(db):
    run = _run(db)
    first = db.query(TemporalCommandOutbox).filter_by(run_id=run.id).one()
    second = enqueue_start(db, run)
    assert first.id == second.id
    assert first.workflow_id == TemporalWorkflowRunner.workflow_id(run.tenant_id, run.id)


def test_dispatcher_starts_workflow_and_completes_command(db, monkeypatch):
    run = _run(db)
    calls = []

    async def start(self, **kwargs):
        calls.append(kwargs)
        return TemporalStartResult(
            workflow_id=TemporalWorkflowRunner.workflow_id(kwargs["tenant_id"], kwargs["run_id"]),
            run_id="temporal-run-id",
            status="scheduled",
        )

    monkeypatch.setattr(TemporalWorkflowRunner, "start_enterprise_run", start)
    assert asyncio.run(dispatch_one_temporal_command()) is True
    db.expire_all()
    command = db.query(TemporalCommandOutbox).filter_by(run_id=run.id).one()
    refreshed = db.get(WorkflowRun, run.id)
    assert command.status == "completed"
    assert command.attempt_count == 1
    assert refreshed.status == "scheduled"
    assert refreshed.temporal_run_id == "temporal-run-id"
    assert calls[0]["demand"] == run.demand


def test_signal_and_cancel_commands_have_stable_keys(db):
    run = _run(db)
    signal = enqueue_signal(
        db,
        run,
        signal_name="human_decision",
        payload={"decision": "approved", "comment": "must stay tenant scoped"},
        decision_key="approval-1",
    )
    cancel = enqueue_cancel(db, run)
    db.flush()
    assert signal.deduplication_key == f"temporal:signal:{run.id}:approval-1"
    assert signal.payload_json == {"decision": "approved"}
    assert cancel.deduplication_key == f"temporal:cancel:{run.id}"


def test_dispatch_failure_is_persisted_for_retry(db, monkeypatch):
    run = _run(db)

    async def fail(self, **kwargs):
        raise RuntimeError("temporal unavailable")

    monkeypatch.setattr(TemporalWorkflowRunner, "start_enterprise_run", fail)
    assert asyncio.run(dispatch_one_temporal_command()) is True
    db.expire_all()
    command = db.query(TemporalCommandOutbox).filter_by(run_id=run.id).one()
    assert command.status == "pending"
    assert command.attempt_count == 1
    assert command.next_attempt_at is not None
    assert "temporal unavailable" in command.last_error


def test_cancel_reconciles_closed_workflow_without_provider_thread(db, monkeypatch):
    run = _run(db)
    start = db.query(TemporalCommandOutbox).filter_by(run_id=run.id, command_type="start").one()
    start.status = "completed"
    run.status = "cancel_requested"
    control = AgentRunState(
        id=str(uuid.uuid4()),
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name="RUN_CONTROL",
        status="cancel_requested",
        outputs_json=[],
    )
    db.add(control)
    enqueue_cancel(db, run)
    db.commit()

    async def closed(self, workflow_id):
        return True

    monkeypatch.setattr(TemporalWorkflowRunner, "is_workflow_closed", closed)
    assert asyncio.run(dispatch_one_temporal_command()) is True
    db.expire_all()
    cancel = db.query(TemporalCommandOutbox).filter_by(run_id=run.id, command_type="cancel").one()
    assert cancel.status == "completed"
    assert db.get(WorkflowRun, run.id).status == "cancelled"
    assert db.get(WorkflowSlot, run.id) is None
