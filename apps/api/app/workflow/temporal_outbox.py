import asyncio
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal, set_tenant_context
from app.events.event_service import emit_event
from app.models import (
    AgentRunState,
    Artifact,
    FileChange,
    HomologationPackage,
    EngagementDependency,
    ServiceDeliverable,
    ServiceAcceptanceCheck,
    ServiceExecution,
    ServiceWorkItem,
    TemporalCommandOutbox,
    Tenant,
    ModelCall,
    PluginInvocation,
    QualityGate,
    TestReport,
    WorkflowRun,
    WorkflowSlot,
    utcnow,
)
from app.agents.ai_native_contracts import stable_hash
from app.providers.temporal_runner import TemporalWorkflowRunner


COMMAND_LEASE = timedelta(minutes=2)
MAX_RETRY_DELAY_SECONDS = 300
MAX_COMMAND_ATTEMPTS = 8
ACTIVE_SERVICE_EXECUTION_STATUSES = {
    "dispatch_pending", "running", "delegated", "cancel_pending",
}
_last_scheduled_tenant = ""


class CancellationAwaitingProvider(RuntimeError):
    pass


def _service_execution_run(db: Session, execution: ServiceExecution) -> Optional[WorkflowRun]:
    run_id = str((execution.evidence_json or {}).get("workflow_run_id") or "")
    if not run_id and execution.deliverable_id:
        deliverable = db.query(ServiceDeliverable).filter_by(
            id=execution.deliverable_id,
            tenant_id=execution.tenant_id,
        ).first()
        run_id = str(deliverable.run_id or "") if deliverable else ""
    return db.query(WorkflowRun).filter_by(
        id=run_id,
        tenant_id=execution.tenant_id,
    ).first() if run_id else None


def _service_execution_deliverables(db: Session, execution: ServiceExecution) -> list[ServiceDeliverable]:
    linked_ids = list((execution.evidence_json or {}).get("linked_deliverable_ids") or [])
    if not linked_ids and execution.deliverable_id:
        linked_ids = [execution.deliverable_id]
    if not linked_ids:
        return []
    rows = db.query(ServiceDeliverable).filter(
        ServiceDeliverable.tenant_id == execution.tenant_id,
        ServiceDeliverable.engagement_id == execution.engagement_id,
        ServiceDeliverable.id.in_(linked_ids),
    ).all()
    by_id = {row.id: row for row in rows}
    return [by_id[item_id] for item_id in linked_ids if item_id in by_id]


def _active_tenant_ids() -> list[str]:
    """Return scheduler control identities without exposing tenant data.

    PostgreSQL production roles remain subject to FORCE RLS. The migration-
    owned function is the sole cross-tenant scheduler surface and returns only
    active tenant IDs; every subsequent read and mutation sets tenant context.
    """
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            return list(db.execute(text("SELECT tenant_id FROM public.asf_active_tenant_ids() ORDER BY tenant_id")).scalars())
        return [
            row.id
            for row in db.query(Tenant)
            .filter_by(status="active")
            .order_by(Tenant.id)
            .execution_options(include_all_tenants=True)
            .all()
        ]
    finally:
        db.close()


def enqueue_temporal_command(
    db: Session,
    *,
    tenant_id: str,
    run_id: Optional[str],
    aggregate_type: str = "workflow_run",
    aggregate_id: str = "",
    command_type: str,
    workflow_id: str,
    deduplication_key: str,
    signal_name: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> TemporalCommandOutbox:
    existing = db.query(TemporalCommandOutbox).filter_by(deduplication_key=deduplication_key).first()
    if existing:
        if (
            existing.tenant_id != tenant_id
            or existing.run_id != run_id
            or existing.aggregate_type != aggregate_type
            or existing.aggregate_id != (aggregate_id or run_id or "")
            or existing.command_type != command_type
        ):
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
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id or run_id or "",
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
        runner = TemporalWorkflowRunner()
        reconciled = False
        if command.aggregate_type == "service_execution":
            execution = db.query(ServiceExecution).filter_by(
                id=command.aggregate_id, tenant_id=command.tenant_id
            ).first()
            if not execution:
                raise RuntimeError(f"Temporal outbox service execution not found: {command.aggregate_id}")
            if command.command_type == "start":
                result = await runner.start_service_execution(
                    tenant_id=execution.tenant_id, execution_id=execution.id,
                    workflow_id=command.workflow_id,
                )
                execution.temporal_workflow_id = result.workflow_id
                execution.temporal_run_id = result.run_id
                if execution.status != "cancel_pending":
                    execution.status = "dispatch_pending"
                execution.record_version += 1
            elif command.command_type == "cancel":
                if not await runner.is_workflow_closed(command.workflow_id):
                    await runner.cancel(command.workflow_id)
                if not await runner.is_workflow_closed(command.workflow_id):
                    raise CancellationAwaitingProvider(
                        "Service execution cancellation is waiting for Temporal terminal confirmation"
                    )
                technical_run = _service_execution_run(db, execution)
                if technical_run and technical_run.status not in {
                    "failed", "cancelled", "approved_for_homologation", "synthetic_approved_for_homologation",
                }:
                    raise CancellationAwaitingProvider(
                        "Service execution cancellation is waiting for the delegated AI-native workflow"
                    )
                execution.status = "cancelled"
                execution.finished_at = utcnow()
                execution.record_version += 1
                item = db.query(ServiceWorkItem).filter_by(
                    id=execution.work_item_id, tenant_id=execution.tenant_id
                ).first()
                if item:
                    item.status = "cancelled"
                    item.blocked_reason = ""
                    item.completed_at = utcnow()
                    item.record_version += 1
                from app.service_delivery.service import actor_event

                actor_event(
                    db, tenant_id=execution.tenant_id, actor_user_id="system",
                    aggregate_type="service_execution", aggregate_id=execution.id,
                    event_type="service_execution.cancellation_confirmed",
                    correlation_id=command.workflow_id,
                    idempotency_key=f"service-execution:{execution.id}:cancellation-confirmed",
                    payload={"summary": "Temporal confirmed terminal cancellation; service slot released"},
                )
            else:
                raise RuntimeError(f"Unsupported service execution command: {command.command_type}")
            from app.service_delivery.service import actor_event

            actor_event(
                db, tenant_id=execution.tenant_id, actor_user_id="system",
                aggregate_type="service_execution", aggregate_id=execution.id,
                event_type="service_execution.temporal_command_dispatched",
                correlation_id=command.workflow_id,
                idempotency_key=f"service-execution:{execution.id}:temporal:{command.id}",
                payload={"summary": f"Temporal {command.command_type} command dispatched", "command_id": command.id},
            )
            run = None
        else:
            run = db.query(WorkflowRun).filter_by(id=command.run_id, tenant_id=command.tenant_id).first()
            if not run:
                raise RuntimeError(f"Temporal outbox run not found: {command.run_id}")
        if command.aggregate_type != "service_execution" and command.command_type == "start":
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
        elif command.aggregate_type != "service_execution" and command.command_type == "signal":
            if await runner.is_workflow_closed(command.workflow_id):
                reconciled = True
            else:
                try:
                    await runner.signal(command.workflow_id, command.signal_name, command.payload_json or {})
                except Exception:
                    if not await runner.is_workflow_closed(command.workflow_id):
                        raise
                    reconciled = True
        elif command.aggregate_type != "service_execution" and command.command_type == "cancel":
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
        elif command.aggregate_type != "service_execution":
            raise RuntimeError(f"Unsupported Temporal outbox command: {command.command_type}")

        command.status = "completed"
        command.completed_at = utcnow()
        command.lease_expires_at = None
        command.last_error = ""
        if run:
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
            exhausted = command.attempt_count >= MAX_COMMAND_ATTEMPTS
            command.status = "failed" if exhausted else "pending"
            command.next_attempt_at = utcnow() + timedelta(seconds=delay)
            command.lease_expires_at = None
            command.last_error = str(exc)[:4000]
            run = db.query(WorkflowRun).filter_by(id=command.run_id, tenant_id=command.tenant_id).first() if command.run_id else None
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
            if command.aggregate_type == "service_execution":
                execution = db.query(ServiceExecution).filter_by(
                    id=command.aggregate_id, tenant_id=command.tenant_id
                ).first()
                if execution and exhausted:
                    from app.service_delivery.service import actor_event

                    execution.status = "failed"
                    execution.last_error = str(exc)[:4000]
                    execution.finished_at = utcnow()
                    execution.record_version += 1
                    item = db.query(ServiceWorkItem).filter_by(
                        id=execution.work_item_id, tenant_id=execution.tenant_id
                    ).first()
                    if item:
                        item.status = "blocked"
                        item.blocked_reason = "Temporal dispatch failed after bounded retries"
                        item.record_version += 1
                    actor_event(
                        db, tenant_id=execution.tenant_id, actor_user_id="system",
                        aggregate_type="service_execution", aggregate_id=execution.id,
                        event_type="service_execution.dispatch_failed", correlation_id=command.workflow_id,
                        idempotency_key=f"service-execution:{execution.id}:dispatch-failed",
                        payload={"summary": "Temporal dispatch failed after bounded retries", "attempts": command.attempt_count},
                    )
            db.commit()
        return True
    finally:
        db.close()
    return True


def schedule_one_service_execution() -> bool:
    """Persist one fair, capacity-bounded dispatch decision.

    The global scan contains only control state. Each tenant row is loaded and
    mutated under that tenant's RLS context.
    """
    global _last_scheduled_tenant
    tenant_ids = _active_tenant_ids()
    if not tenant_ids:
        return False
    if _last_scheduled_tenant in tenant_ids:
        pivot = tenant_ids.index(_last_scheduled_tenant) + 1
        tenant_ids = tenant_ids[pivot:] + tenant_ids[:pivot]
    snapshots: list[tuple[str, int, Optional[str], Optional[str]]] = []
    global_active = 0
    priority = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            for dependency in db.query(EngagementDependency).filter_by(
                tenant_id=tenant_id, status="pending"
            ).all():
                upstream_deliverables = db.query(ServiceDeliverable).filter_by(
                    tenant_id=tenant_id, engagement_id=dependency.depends_on_engagement_id
                ).all()
                upstream_checks = db.query(ServiceAcceptanceCheck).filter_by(
                    tenant_id=tenant_id, engagement_id=dependency.depends_on_engagement_id
                ).all()
                if (
                    upstream_deliverables
                    and upstream_checks
                    and all(row.status == "delivered" for row in upstream_deliverables)
                    and all(row.status in {"passed", "external_constraint"} for row in upstream_checks)
                ):
                    dependency.status = "satisfied"
                    dependency.evidence_refs_json = [f"engagement:{dependency.depends_on_engagement_id}"]
            active = db.query(ServiceExecution).filter(
                ServiceExecution.tenant_id == tenant_id,
                ServiceExecution.status.in_(ACTIVE_SERVICE_EXECUTION_STATUSES),
            ).count()
            global_active += active
            candidates = db.query(ServiceExecution).filter_by(tenant_id=tenant_id, status="queued").all()
            ranked = []
            for execution in candidates:
                pending_dependency = db.query(EngagementDependency).filter_by(
                    tenant_id=tenant_id, engagement_id=execution.engagement_id, status="pending"
                ).first()
                if pending_dependency:
                    continue
                item = db.query(ServiceWorkItem).filter_by(id=execution.work_item_id, tenant_id=tenant_id).first()
                if item:
                    ranked.append((priority.get(item.priority, 9), item.due_at or utcnow(), execution.created_at, execution.id, item, execution))
            ranked.sort(key=lambda row: row[:4])
            snapshots.append((tenant_id, active, ranked[0][5].id if ranked else None, ranked[0][4].id if ranked else None))
            db.commit()
        finally:
            db.close()
    settings = get_settings()
    if global_active >= settings.service_wip_global_limit:
        return False
    selected = next(
        ((tenant_id, execution_id, item_id) for tenant_id, active, execution_id, item_id in snapshots
         if execution_id and item_id and active < settings.service_wip_per_tenant_limit),
        None,
    )
    if not selected:
        return False
    tenant_id, selected_execution_id, _ = selected
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        execution = db.query(ServiceExecution).filter_by(id=selected_execution_id, tenant_id=tenant_id, status="queued").first()
        if not execution:
            return False
        item = db.query(ServiceWorkItem).filter_by(id=execution.work_item_id, tenant_id=tenant_id).first()
        if not item:
            return False
        execution.status = "dispatch_pending"
        execution.temporal_workflow_id = (
            f"{TemporalWorkflowRunner.service_execution_workflow_id(tenant_id, execution.id)}"
            f"-attempt-{execution.attempt_count + 1}"
        )
        execution.record_version += 1
        item.status = "in_progress"
        item.started_at = item.started_at or utcnow()
        item.record_version += 1
        enqueue_temporal_command(
            db, tenant_id=tenant_id, run_id=None, aggregate_type="service_execution",
            aggregate_id=execution.id, command_type="start", workflow_id=execution.temporal_workflow_id,
            deduplication_key=f"temporal:service-execution:start:{execution.id}:{execution.attempt_count + 1}",
        )
        db.commit()
        _last_scheduled_tenant = tenant_id
        return True
    finally:
        db.close()


def _technical_delivery_content(
    deliverable: ServiceDeliverable,
    run: WorkflowRun,
    artifact_refs: list[str],
    technical_evidence: Optional[Dict[str, Any]] = None,
) -> dict:
    technical_evidence = technical_evidence or {}
    evidence_lines = "\n".join(
        f"- Artifact `{artifact_id}`"
        for artifact_id in artifact_refs[:20]
    ) or "- Workflow terminal persistido sem artifact adicional."
    technical_markdown = (
        f"# {deliverable.title}\n\n"
        "## Objetivo\n\n"
        f"Consolidar a execução técnica contratada para **{deliverable.title}** em uma revisão "
        "rastreável, sem substituir a conferência e a decisão humana do VP.\n\n"
        "## Conteúdo\n\n"
        f"A fábrica AI-native executou o workflow `{run.id}` até o estado terminal `{run.status}`. "
        f"O trabalho corresponde ao escopo: {deliverable.description or 'entregável técnico contratado'}. "
        "Código, testes, quality gates, rastreabilidade, FileChange e pacote de homologação permanecem "
        "nas evidências autoritativas da run; este documento é o índice de entrega para revisão.\n\n"
        "## Evidências\n\n"
        f"- Workflow run: `workflow_run:{run.id}`\n"
        f"- Artifacts vinculados: {len(artifact_refs)}\n"
        f"- FileChanges com diff: {technical_evidence.get('diffs_with_content', 0)}\n"
        f"- Test reports aprovados: {len(technical_evidence.get('test_report_ids') or [])}\n"
        f"- Quality gates aprovados: {technical_evidence.get('quality_gates_passed', 0)}/17\n"
        f"- HRS: {technical_evidence.get('hrs', getattr(run, 'homologation_readiness_score', 0) or 0)}\n"
        f"{evidence_lines}\n\n"
        "## Riscos e limitações\n\n"
        "O estado terminal da fábrica comprova a execução técnica registrada, mas não comprova sozinho "
        "aderência comercial, aceite do cliente ou resultado futuro. O VP deve conferir gates, HRS, "
        "Ponytail, Cavekit, diffs e limitações antes de decidir.\n\n"
        "## Próximos passos\n\n"
        "O owner confere a proveniência e a completude do pacote. Em seguida, o VP pode solicitar "
        "ajustes, rejeitar ou aprovar explicitamente esta revisão; nenhuma decisão é automática.\n"
    )
    return {
        "title": deliverable.title,
        "executive_summary": (
            "Índice rastreável da execução técnica concluída pela fábrica e encaminhada para revisão humana."
        ),
        "content_markdown": technical_markdown,
        "evidence_claims": [
            f"A run {run.id} alcançou o estado persistido {run.status}.",
            f"{len(artifact_refs)} artifact(s) da run foram vinculados à revisão.",
        ],
        "risks": [
            "Aceite comercial e resultado futuro continuam dependentes de decisão e validação humanas."
        ],
        "next_actions": [
            "Conferir gates, HRS, Ponytail, Cavekit, diffs e pacote antes da decisão do VP."
        ],
        "technical_run_id": run.id,
        "technical_evidence": technical_evidence,
        "validation_mode": "synthetic" if run.status.startswith("synthetic_") else "real",
    }


def _technical_run_evidence(
    db: Session,
    *,
    run: WorkflowRun,
    artifact_refs: list[str],
) -> dict[str, Any]:
    gates = db.query(QualityGate).filter_by(
        tenant_id=run.tenant_id,
        run_id=run.id,
    ).all()
    changes = db.query(FileChange).filter_by(
        tenant_id=run.tenant_id,
        run_id=run.id,
    ).all()
    test_reports = db.query(TestReport).filter_by(
        tenant_id=run.tenant_id,
        run_id=run.id,
        status="passed",
    ).all()
    package = (
        db.query(HomologationPackage)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(HomologationPackage.created_at.desc())
        .first()
    )
    plugins = db.query(PluginInvocation).filter_by(
        tenant_id=run.tenant_id,
        run_id=run.id,
    ).all()

    def plugin_status(name: str) -> str:
        rows = [row for row in plugins if row.plugin_name == name]
        return (
            "terminal"
            if rows
            and all(
                row.status in {"completed", "not_applicable"}
                and bool(str(row.output_hash or ""))
                for row in rows
            )
            else "missing_or_non_terminal"
        )

    manifest = package.manifest_json if package else {}
    return {
        "validation_mode": (
            "synthetic" if run.status.startswith("synthetic_") else "real"
        ),
        "quality_gates_passed": sum(
            gate.status in {"passed", "synthetic_passed"} for gate in gates
        ),
        "quality_gate_ids": sorted(gate.gate_id for gate in gates),
        "hrs": float(run.homologation_readiness_score or 0.0),
        "ponytail_status": plugin_status("ponytail"),
        "cavekit_status": plugin_status("cavekit"),
        "file_changes": len(changes),
        "diffs_with_content": sum(bool(str(change.diff or "").strip()) for change in changes),
        "code_artifact_refs": [f"file_change:{change.id}" for change in changes],
        "artifact_refs": list(artifact_refs),
        "test_report_ids": [report.id for report in test_reports],
        "homologation_package_id": package.id if package else "",
        "delivery_package_sha256": stable_hash(manifest) if package else "",
    }


def reconcile_technical_service_executions() -> None:
    tenant_ids = _active_tenant_ids()
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            executions = db.query(ServiceExecution).filter_by(tenant_id=tenant_id, status="delegated").all()
            for execution in executions:
                deliverables = _service_execution_deliverables(db, execution)
                run = _service_execution_run(db, execution)
                if not run or not deliverables:
                    continue
                item = db.query(ServiceWorkItem).filter_by(id=execution.work_item_id, tenant_id=tenant_id).first()
                if run.status in {"approved_for_homologation", "synthetic_approved_for_homologation"}:
                    from app.service_delivery.os_service import ServiceDeliveryOSService

                    artifact_refs = [
                        row.id for row in db.query(Artifact).filter_by(
                            tenant_id=tenant_id, run_id=run.id
                        ).order_by(Artifact.created_at).all()
                    ]
                    technical_evidence = _technical_run_evidence(
                        db,
                        run=run,
                        artifact_refs=artifact_refs,
                    )
                    revision_ids: list[str] = []
                    approval_ids: list[str] = []
                    for deliverable in deliverables:
                        revision = ServiceDeliveryOSService().create_revision(
                            db, tenant_id=tenant_id, actor_user_id="system", deliverable_id=deliverable.id,
                            content=_technical_delivery_content(
                                deliverable,
                                run,
                                artifact_refs,
                                technical_evidence,
                            ),
                            artifact_refs=artifact_refs, evidence_refs=[f"workflow_run:{run.id}"],
                            model_call_id="", correlation_id=execution.temporal_workflow_id,
                            event_idempotency_key=(
                                f"service-execution:{execution.id}:technical-revision:{deliverable.id}"
                            ),
                        )
                        approval = ServiceDeliveryOSService().submit_deliverable(
                            db,
                            tenant_id=tenant_id,
                            actor_user_id="system",
                            deliverable_id=deliverable.id,
                            expected_version=deliverable.record_version,
                            comment="A fábrica técnica concluiu os gates e produziu uma revisão; decisão humana obrigatória.",
                            correlation_id=execution.temporal_workflow_id,
                            event_idempotency_key=(
                                f"service-execution:{execution.id}:technical-submitted:{deliverable.id}"
                            ),
                        )
                        revision_ids.append(revision.id)
                        approval_ids.append(approval.id)
                    execution.status = "awaiting_review"
                    execution.finished_at = utcnow()
                    execution.evidence_json = {
                        **(execution.evidence_json or {}),
                        "deliverable_revision_id": revision_ids[0],
                        "approval_id": approval_ids[0],
                        "deliverable_revision_ids": revision_ids,
                        "approval_ids": approval_ids,
                        "technical_evidence": technical_evidence,
                    }
                    execution.estimated_cost_usd = float(
                        sum(
                            row.estimated_cost_usd or 0.0
                            for row in db.query(ModelCall).filter_by(tenant_id=tenant_id, run_id=run.id).all()
                        )
                    )
                    execution.record_version += 1
                    if item:
                        item.status = "completed"
                        item.completed_at = utcnow()
                        item.record_version += 1
                elif run.status in {"failed", "cancelled", "rejected", "blocked"}:
                    execution.status = "failed"
                    execution.last_error = f"Delegated workflow ended as {run.status}"
                    execution.finished_at = utcnow()
                    execution.record_version += 1
                    if item:
                        item.status = "blocked"
                        item.blocked_reason = execution.last_error
                        item.record_version += 1
            db.commit()
        finally:
            db.close()


async def run_temporal_outbox_dispatcher(poll_interval_seconds: float = 1.0) -> None:
    while True:
        reconcile_technical_service_executions()
        scheduled = schedule_one_service_execution()
        dispatched = await dispatch_one_temporal_command()
        if not dispatched and not scheduled:
            await asyncio.sleep(poll_interval_seconds)
