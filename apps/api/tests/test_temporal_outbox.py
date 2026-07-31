import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.db.session import SessionLocal, engine
from app.auth.dependencies import Principal
from app.api import routes_runs
from app.models import (
    AgentRunState,
    Base,
    Engagement,
    FileChange,
    HomologationPackage,
    PluginInvocation,
    Project,
    QualityGate,
    ServiceExecution,
    ServiceWorkItem,
    TemporalCommandOutbox,
    Tenant,
    TestReport as ModelTestReport,
    WorkflowRun,
    WorkflowSlot,
)
from app.providers.temporal_runner import TemporalStartResult, TemporalWorkflowRunner
from app.service_delivery.deliverable_quality import evaluate_deliverable_contract
from app.services.run_service import provider
from app.workflow import temporal_outbox
from app.workflow.temporal_outbox import (
    _technical_delivery_content,
    _technical_run_evidence,
    dispatch_one_temporal_command,
    enqueue_cancel,
    enqueue_signal,
    enqueue_start,
    enqueue_temporal_command,
)


def test_technical_run_summary_satisfies_the_same_v2_delivery_contract():
    deliverable = SimpleNamespace(
        title="Piloto funcional NovaMec",
        description="Copiloto grounded para um tipo de equipamento e 120 perguntas.",
    )
    run = SimpleNamespace(id="run-novamec-1", status="approved_for_homologation")
    content = _technical_delivery_content(deliverable, run, ["artifact-code", "artifact-tests"])
    evaluation = evaluate_deliverable_contract(
        content=content,
        template={
            "required_sections": [
                "objetivo",
                "conteúdo",
                "evidências",
                "riscos e limitações",
                "próximos passos",
            ],
            "required_evidence": ["artifact_ref", "source_refs", "human_review"],
        },
        evidence_refs=["workflow_run:run-novamec-1"],
        specificity_terms=["NovaMec", "120 perguntas"],
    )

    assert evaluation["passed"] is True
    assert content["validation_mode"] == "real"
    assert content["technical_run_id"] == "run-novamec-1"


def test_technical_run_evidence_links_code_diffs_tests_gates_plugins_and_package(db):
    run = _run(db, tenant_id="metalquote")
    run.status = "approved_for_homologation"
    run.generation_mode = "ai_native_v2"
    run.homologation_readiness_score = 96
    for index in range(17):
        db.add(
            QualityGate(
                id=f"metalquote-gate-{index}",
                tenant_id=run.tenant_id,
                run_id=run.id,
                gate_id=f"gate-{index}",
                name=f"Gate {index}",
                category="quality",
                status="passed",
                score=100,
            )
        )
    db.add(
        FileChange(
            id="metalquote-file-change",
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Engineer",
            file_path="generated_app/backend/app/quote.py",
            change_type="create",
            before_content="",
            after_content="def draft_quote():\n    return {'status': 'pending_vp'}\n",
            diff=(
                "--- /dev/null\n+++ generated_app/backend/app/quote.py\n"
                "@@ -0,0 +1,2 @@\n+def draft_quote():\n+    return {'status': 'pending_vp'}\n"
            ),
        )
    )
    db.add(
        ModelTestReport(
            id="metalquote-test-report",
            tenant_id=run.tenant_id,
            run_id=run.id,
            command="pytest",
            status="passed",
            passed_count=18,
            failed_count=0,
        )
    )
    db.add(
        HomologationPackage(
            id="metalquote-package",
            tenant_id=run.tenant_id,
            run_id=run.id,
            path="delivery/metalquote",
            status="approved",
            manifest_json={
                "source_files": ["generated_app/backend/app/quote.py"],
                "tests": {"final_status": "passed"},
            },
        )
    )
    for plugin_name in ("ponytail", "cavekit"):
        db.add(
            PluginInvocation(
                id=f"metalquote-{plugin_name}",
                tenant_id=run.tenant_id,
                run_id=run.id,
                plugin_name=plugin_name,
                plugin_version="test-pinned",
                source_revision="test-reviewed",
                command="full" if plugin_name == "ponytail" else "check",
                status="completed",
                invocation_key=f"metalquote:{plugin_name}",
                input_hash="a" * 64,
                output_hash="b" * 64,
            )
        )
    db.flush()

    evidence = _technical_run_evidence(
        db,
        run=run,
        artifact_refs=["artifact:architecture", "artifact:security"],
    )

    assert evidence["validation_mode"] == "real"
    assert evidence["quality_gates_passed"] == 17
    assert evidence["hrs"] == 96
    assert evidence["file_changes"] == evidence["diffs_with_content"] == 1
    assert evidence["code_artifact_refs"] == ["file_change:metalquote-file-change"]
    assert evidence["test_report_ids"] == ["metalquote-test-report"]
    assert evidence["homologation_package_id"] == "metalquote-package"
    assert evidence["ponytail_status"] == "terminal"
    assert evidence["cavekit_status"] == "terminal"
    assert len(evidence["delivery_package_sha256"]) == 64


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


def test_run_control_state_is_shared_and_idempotent(db):
    run = _run(db)
    first = provider.control_state(db, run)
    second = provider.control_state(db, run)
    assert first.id == second.id
    assert first.tenant_id == run.tenant_id
    assert first.tools_json == ["pause", "resume", "step", "cancel"]


def test_cancel_requested_run_recreates_missing_temporal_command(db, monkeypatch):
    run = _run(db)
    db.query(TemporalCommandOutbox).delete()
    run.status = "cancel_requested"
    run.temporal_workflow_id = "missing-temporal-workflow"
    db.commit()
    principal = Principal(
        tenant_id=run.tenant_id,
        user_id="owner-user",
        subject="owner-subject",
        email="owner@example.com",
        name="Owner",
        role="owner",
        claims={},
        auth_mode="test",
    )
    monkeypatch.setattr(routes_runs, "_uses_temporal", lambda: True)

    response = asyncio.run(routes_runs.cancel_run(run.id, principal, db))

    assert response["status"] == "cancel_requested"
    command = db.query(TemporalCommandOutbox).filter_by(run_id=run.id, command_type="cancel").one()
    assert command.workflow_id == "missing-temporal-workflow"


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


def test_service_slot_is_released_only_after_temporal_confirms_cancellation(db, monkeypatch):
    tenant_id = "service-cancel-tenant"
    db.add(Tenant(id=tenant_id, name="Service Cancel", slug=tenant_id))
    engagement = Engagement(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id="contract-cancel",
        offering_version_id="offering-cancel", name="Cancellation confirmation",
        status="active", record_version=1,
    )
    item = ServiceWorkItem(
        id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id,
        title="Held service slot", status="in_progress", execution_mode="agent", record_version=1,
    )
    execution = ServiceExecution(
        id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id,
        work_item_id=item.id, status="cancel_pending", execution_mode="agent",
        temporal_workflow_id="service-cancel-workflow", record_version=2,
    )
    db.add_all([engagement, item, execution])
    db.flush()
    enqueue_temporal_command(
        db, tenant_id=tenant_id, run_id=None, aggregate_type="service_execution",
        aggregate_id=execution.id, command_type="cancel", workflow_id=execution.temporal_workflow_id,
        deduplication_key=f"temporal:service-execution:cancel:{execution.id}:1",
    )
    db.commit()

    async def closed(self, workflow_id):
        return True

    monkeypatch.setattr(TemporalWorkflowRunner, "is_workflow_closed", closed)
    assert "cancel_pending" in temporal_outbox.ACTIVE_SERVICE_EXECUTION_STATUSES
    assert asyncio.run(dispatch_one_temporal_command()) is True
    db.expire_all()
    assert db.get(ServiceExecution, execution.id).status == "cancelled"
    assert db.get(ServiceWorkItem, item.id).status == "cancelled"
    command = db.query(TemporalCommandOutbox).filter_by(aggregate_id=execution.id).one()
    assert command.status == "completed"


def test_service_scheduler_proves_five_global_two_per_tenant_and_round_robin(db):
    temporal_outbox._last_scheduled_tenant = ""
    for tenant_id in ("tenant-a", "tenant-b", "tenant-c"):
        db.add(Tenant(id=tenant_id, name=tenant_id, slug=tenant_id))
        engagement = Engagement(
            id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=f"contract-{tenant_id}",
            offering_version_id=f"offering-{tenant_id}", name=f"Engagement {tenant_id}",
            status="active", record_version=1,
        )
        db.add(engagement)
        db.flush()
        for sequence in range(2):
            item = ServiceWorkItem(
                id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id,
                title=f"Item {sequence}", execution_mode="agent", status="queued",
                priority="normal", record_version=1,
            )
            db.add(item)
            db.flush()
            db.add(ServiceExecution(
                id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id,
                work_item_id=item.id, execution_mode="agent", status="queued", record_version=1,
            ))
    db.commit()

    assert [temporal_outbox.schedule_one_service_execution() for _ in range(5)] == [True] * 5
    assert temporal_outbox.schedule_one_service_execution() is False
    db.expire_all()
    active = {
        tenant_id: db.query(ServiceExecution).filter(
            ServiceExecution.tenant_id == tenant_id,
            ServiceExecution.status == "dispatch_pending",
        ).count()
        for tenant_id in ("tenant-a", "tenant-b", "tenant-c")
    }
    assert active == {"tenant-a": 2, "tenant-b": 2, "tenant-c": 1}
    assert db.query(ServiceExecution).filter_by(status="queued").count() == 1
    assert db.query(TemporalCommandOutbox).filter_by(
        aggregate_type="service_execution", command_type="start", status="pending"
    ).count() == 5
