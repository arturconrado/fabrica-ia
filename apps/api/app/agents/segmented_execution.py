"""Durable segmented-output persistence with idempotent units and deterministic assembly."""

from __future__ import annotations

import hashlib
import uuid
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.agents.ai_native_contracts import ArtifactSectionResult, NodePlanResult, OutputUnitDescriptor, stable_hash
from app.models import (
    AgentStepExecution,
    Artifact,
    ArtifactFragment,
    ExecutionUnit,
    WorkflowNodeState,
    WorkflowRun,
    utcnow,
)
from app.providers.object_storage import object_storage
from app.service_delivery.ledger import append_ledger_event


SEGMENTED_PROTOCOL_VERSION = "segmented-output-v1"


class SegmentedExecutionError(RuntimeError):
    pass


def execution_unit_key(
    *, tenant_id: str, run_id: str, node_id: str, iteration: int, unit_key: str, action: str
) -> str:
    """The canonical idempotency identity required by the execution protocol."""

    return "/".join((tenant_id, run_id, node_id, str(iteration), unit_key, action))


class SegmentedExecutionService:
    def get_or_create_unit(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node_state: Optional[WorkflowNodeState],
        step: Optional[AgentStepExecution],
        node_id: str,
        phase: str,
        iteration: int,
        descriptor: OutputUnitDescriptor,
        strategy: str,
        action: str = "execute",
        trace_id: str = "",
        temporal_activity_id: str = "",
    ) -> ExecutionUnit:
        existing = (
            db.query(ExecutionUnit)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                iteration=iteration,
                unit_key=descriptor.key,
                action=action,
            )
            .first()
        )
        descriptor_hash = stable_hash(descriptor.model_dump(mode="json"))
        if existing:
            if existing.input_hash and existing.input_hash != descriptor_hash:
                raise SegmentedExecutionError(f"execution unit {descriptor.key} was replayed with a different descriptor")
            return existing
        unit = ExecutionUnit(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            workflow_node_state_id=node_state.id if node_state else None,
            step_execution_id=step.id if step else None,
            node_id=node_id,
            phase=phase,
            iteration=iteration,
            unit_key=descriptor.key,
            unit_type=descriptor.unit_type,
            strategy=strategy,
            action=action,
            order_index=descriptor.order,
            dependencies_json=list(descriptor.dependencies),
            targets_json=list(descriptor.targets),
            input_budget_tokens=descriptor.input_budget_tokens,
            output_budget_tokens=descriptor.output_budget_tokens,
            input_hash=descriptor_hash,
            trace_id=trace_id,
            temporal_activity_id=temporal_activity_id,
        )
        db.add(unit)
        db.flush()
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="output.unit_planned",
            action="planned",
            payload={"strategy": strategy, "unit_type": unit.unit_type, "order": unit.order_index},
        )
        return unit

    def persist_plan(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node_state: Optional[WorkflowNodeState],
        step: Optional[AgentStepExecution],
        node_id: str,
        phase: str,
        iteration: int,
        plan: NodePlanResult,
        strategy: str,
        trace_id: str = "",
        temporal_activity_id: str = "",
    ) -> list[ExecutionUnit]:
        units = [
            self.get_or_create_unit(
                db,
                run=run,
                node_state=node_state,
                step=step,
                node_id=node_id,
                phase=phase,
                iteration=iteration,
                descriptor=descriptor,
                strategy=strategy,
                trace_id=trace_id,
                temporal_activity_id=temporal_activity_id,
            )
            for descriptor in sorted(plan.units, key=lambda item: item.order)
        ]
        run.executor_protocol_version = SEGMENTED_PROTOCOL_VERSION
        run.trace_id = trace_id or run.trace_id
        run.last_heartbeat_at = utcnow()
        return units

    def start_unit(self, db: Session, *, run: WorkflowRun, unit: ExecutionUnit) -> ExecutionUnit:
        if unit.status == "completed":
            return unit
        completed_dependencies = {
            row.unit_key
            for row in db.query(ExecutionUnit).filter_by(
                tenant_id=unit.tenant_id,
                run_id=unit.run_id,
                node_id=unit.node_id,
                iteration=unit.iteration,
                status="completed",
            )
        }
        missing = set(unit.dependencies_json or []).difference(completed_dependencies)
        if missing:
            raise SegmentedExecutionError(f"execution unit {unit.unit_key} is blocked by {sorted(missing)}")
        if unit.attempt_count >= unit.max_attempts:
            raise SegmentedExecutionError(f"execution unit {unit.unit_key} exhausted {unit.max_attempts} attempts")
        unit.attempt_count += 1
        unit.status = "running"
        unit.started_at = unit.started_at or utcnow()
        unit.last_heartbeat_at = utcnow()
        unit.error = ""
        run.last_heartbeat_at = unit.last_heartbeat_at
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="output.unit_started",
            action=f"started:{unit.attempt_count}",
            payload={"attempt": unit.attempt_count},
        )
        return unit

    def heartbeat(self, db: Session, *, run: WorkflowRun, unit: ExecutionUnit) -> None:
        unit.last_heartbeat_at = utcnow()
        run.last_heartbeat_at = unit.last_heartbeat_at
        db.flush()

    def continue_truncated_unit(self, db: Session, *, run: WorkflowRun, unit: ExecutionUnit) -> None:
        if unit.continuation_count >= unit.max_continuations:
            raise SegmentedExecutionError(
                f"execution unit {unit.unit_key} exhausted {unit.max_continuations} truncation continuations"
            )
        unit.continuation_count += 1
        unit.finish_reason = "length"
        unit.status = "pending"
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="output.unit_continuation_requested",
            action=f"continuation:{unit.continuation_count}",
            payload={"continuation": unit.continuation_count, "finish_reason": "length"},
        )

    def complete_unit(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        unit: ExecutionUnit,
        output: dict,
        model_call_id: str,
        finish_reason: str = "stop",
    ) -> ExecutionUnit:
        output_hash = stable_hash(output)
        if unit.status == "completed":
            if unit.output_hash != output_hash:
                raise SegmentedExecutionError(f"completed unit {unit.unit_key} cannot be replaced by different output")
            return unit
        if finish_reason == "length":
            self.continue_truncated_unit(db, run=run, unit=unit)
            return unit
        unit.status = "completed"
        unit.model_call_id = model_call_id
        unit.output_json = output
        unit.output_hash = output_hash
        unit.finish_reason = finish_reason
        unit.finished_at = utcnow()
        unit.last_heartbeat_at = unit.finished_at
        run.last_heartbeat_at = unit.finished_at
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="output.unit_completed",
            action="completed",
            payload={"model_call_id": model_call_id, "output_hash": output_hash, "finish_reason": finish_reason},
        )
        return unit

    def fail_unit(self, db: Session, *, run: WorkflowRun, unit: ExecutionUnit, error: Exception) -> None:
        unit.status = "failed"
        unit.error = str(error)[:8000]
        unit.finished_at = utcnow()
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="output.unit_failed",
            action=f"failed:{unit.attempt_count}",
            payload={"attempt": unit.attempt_count, "error": unit.error[:1000]},
        )

    def persist_artifact_fragment(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        unit: ExecutionUnit,
        result: ArtifactSectionResult,
        model_call_id: str,
    ) -> ArtifactFragment:
        checksum = hashlib.sha256(result.markdown.encode("utf-8")).hexdigest()
        existing = (
            db.query(ArtifactFragment)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=unit.node_id,
                iteration=unit.iteration,
                artifact_name=result.artifact_name,
                section_key=result.section_key,
                order_index=result.order,
            )
            .first()
        )
        if existing:
            if existing.checksum != checksum or existing.model_call_id != model_call_id:
                raise SegmentedExecutionError("artifact fragment replay does not match its persisted provenance")
            return existing
        fragment = ArtifactFragment(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            execution_unit_id=unit.id,
            model_call_id=model_call_id,
            node_id=unit.node_id,
            iteration=unit.iteration,
            artifact_name=result.artifact_name,
            artifact_type=result.artifact_type,
            audience=result.audience,
            section_key=result.section_key,
            section_title=result.section_title,
            order_index=result.order,
            content=result.markdown,
            citations_json=list(result.citations),
            checksum=checksum,
            is_final=result.final,
        )
        db.add(fragment)
        db.flush()
        self._event(
            db,
            run=run,
            unit=unit,
            event_type="artifact.fragment_created",
            action=f"fragment:{fragment.id}",
            payload={
                "fragment_id": fragment.id,
                "artifact_name": fragment.artifact_name,
                "section_key": fragment.section_key,
                "checksum": checksum,
                "model_call_id": model_call_id,
            },
        )
        return fragment

    def assemble_artifact(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node_id: str,
        iteration: int,
        artifact_name: str,
        step_execution_id: str,
    ) -> Artifact:
        fragments = (
            db.query(ArtifactFragment)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                iteration=iteration,
                artifact_name=artifact_name,
            )
            .order_by(ArtifactFragment.order_index.asc(), ArtifactFragment.id.asc())
            .all()
        )
        if not fragments:
            raise SegmentedExecutionError(f"artifact {artifact_name} has no persisted fragments")
        orders = [fragment.order_index for fragment in fragments]
        if orders != list(range(len(orders))):
            raise SegmentedExecutionError(f"artifact {artifact_name} has missing or duplicate section order")
        if len(fragments) > 12:
            raise SegmentedExecutionError(f"artifact {artifact_name} exceeds the 12-section protocol limit")
        content = "\n\n".join(fragment.content.strip() for fragment in fragments).strip() + "\n"
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = (
            db.query(Artifact)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, name=artifact_name)
            .all()
        )
        protocol_artifact = next(
            (
                artifact
                for artifact in existing
                if (artifact.metadata_json or {}).get("executor_protocol_version") == SEGMENTED_PROTOCOL_VERSION
                and int((artifact.metadata_json or {}).get("iteration") or 0) == iteration
            ),
            None,
        )
        fragment_ids = [fragment.id for fragment in fragments]
        model_call_ids = list(dict.fromkeys(fragment.model_call_id for fragment in fragments))
        if protocol_artifact:
            if (protocol_artifact.metadata_json or {}).get("sha256") != checksum:
                raise SegmentedExecutionError(f"assembled artifact {artifact_name} cannot be overwritten")
            return protocol_artifact
        artifact = Artifact(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id=node_id,
            artifact_type=fragments[0].artifact_type,
            name=artifact_name,
            path=f"docs/{artifact_name}",
            content=content,
            audience=fragments[0].audience,
            evidence_classification="real",
            source_refs_json=[*fragment_ids, *model_call_ids, step_execution_id],
            model_call_id=model_call_ids[-1],
            step_execution_id=step_execution_id,
            metadata_json={
                "executor_protocol_version": SEGMENTED_PROTOCOL_VERSION,
                "iteration": iteration,
                "sha256": checksum,
                "fragment_ids": fragment_ids,
                "model_call_ids": model_call_ids,
                "provenance": "deterministic_fragment_assembly",
            },
        )
        db.add(artifact)
        db.flush()
        for fragment in fragments:
            fragment.artifact_id = artifact.id
        storage_key = object_storage.put_text(
            run.tenant_id,
            run.id,
            "artifacts",
            artifact_name,
            content,
            content_type="text/markdown; charset=utf-8" if artifact.artifact_type == "markdown" else "text/plain; charset=utf-8",
        )
        artifact.metadata_json = {**artifact.metadata_json, "storage_key": storage_key or ""}
        append_ledger_event(
            db,
            tenant_id=run.tenant_id,
            aggregate_type="run",
            aggregate_id=run.id,
            event_type="artifact.assembled",
            actor_user_id="system:segmented-executor",
            correlation_id=run.trace_id or run.id,
            idempotency_key=execution_unit_key(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                iteration=iteration,
                unit_key=artifact_name,
                action="assemble",
            ),
            payload={
                "summary": f"{artifact_name} assembled deterministically from {len(fragments)} fragments",
                "run_id": run.id,
                "node_id": node_id,
                "artifact_id": artifact.id,
                "fragment_ids": fragment_ids,
                "sha256": checksum,
            },
            project_agent_event=True,
        )
        return artifact

    @staticmethod
    def _event(
        db: Session,
        *,
        run: WorkflowRun,
        unit: ExecutionUnit,
        event_type: str,
        action: str,
        payload: dict,
    ) -> None:
        append_ledger_event(
            db,
            tenant_id=run.tenant_id,
            aggregate_type="execution_unit",
            aggregate_id=unit.id,
            event_type=event_type,
            actor_user_id="system:segmented-executor",
            correlation_id=unit.trace_id or run.trace_id or run.id,
            idempotency_key=execution_unit_key(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=unit.node_id,
                iteration=unit.iteration,
                unit_key=unit.unit_key,
                action=action,
            ),
            payload={
                "summary": event_type.replace(".", " "),
                "run_id": run.id,
                "node_id": unit.node_id,
                "phase": unit.phase,
                "execution_unit_id": unit.id,
                "unit_key": unit.unit_key,
                "status": unit.status,
                **payload,
            },
            project_agent_event=True,
        )


def unit_descriptors_for_targets(
    *, unit_type: str, targets: Iterable[str], output_budget_tokens: int
) -> list[OutputUnitDescriptor]:
    """Deterministic fallback manifest used only when targets are already defined by the workflow."""

    return [
        OutputUnitDescriptor(
            key=f"{unit_type}-{index:02d}",
            unit_type=unit_type,
            targets=[target],
            order=index - 1,
            dependencies=[f"{unit_type}-{index - 1:02d}"] if index > 1 else [],
            output_budget_tokens=output_budget_tokens,
        )
        for index, target in enumerate(targets, start=1)
    ]
