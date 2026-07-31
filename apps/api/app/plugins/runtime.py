"""Idempotent production plugin activation and audit records."""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agents.ai_native_contracts import stable_hash
from app.events.event_service import emit_event
from app.models import PluginInvocation, WorkflowRun
from app.plugins.cavekit import CAVEKIT_SOURCE_REVISION, CAVEKIT_VERSION, CavekitPolicy
from app.plugins.ponytail import PONYTAIL_SOURCE_REVISION, PONYTAIL_VERSION, PonytailPolicy


class FactoryPluginRuntime:
    """Curates third-party instructions per task and records every activation."""

    def manifests(self) -> list[dict[str, Any]]:
        return [PonytailPolicy.manifest(), CavekitPolicy.manifest()]

    def validate_execution_manifest(self, execution: dict[str, Any]) -> None:
        configured = execution.get("plugins") or {}
        if configured.get("mandatory") is not True or configured.get("fail_closed") is not True:
            raise ValueError("production policies require mandatory fail-closed production plugins")
        if configured.get("automatic_updates") is not False:
            raise ValueError("production plugin updates must remain disabled")
        expected = {manifest["name"]: manifest for manifest in self.manifests()}
        for name, manifest in expected.items():
            plugin = configured.get(name) or {}
            if str(plugin.get("version") or "") != manifest["version"]:
                raise ValueError(f"{name} version does not match the audited runtime")
            if str(plugin.get("source_revision") or "") != manifest["source_revision"]:
                raise ValueError(f"{name} revision does not match the audited runtime")

    def prompt_for_node(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        iteration: int,
        action: str,
        execution_unit_id: str = "",
    ) -> str:
        node_id = str(node.get("id") or "")
        phase = str(node.get("phase") or "")
        prompt_parts: list[str] = []
        mode, commands, ponytail_prompt = PonytailPolicy.prompt_for_node(node)
        if commands:
            prompt_parts.append(ponytail_prompt)
            for command in commands:
                self._record(
                    db,
                    run=run,
                    plugin_name="ponytail",
                    plugin_version=PONYTAIL_VERSION,
                    source_revision=PONYTAIL_SOURCE_REVISION,
                    command=command,
                    mode=mode,
                    node_id=node_id,
                    phase=phase,
                    iteration=iteration,
                    action=action,
                    execution_unit_id=execution_unit_id,
                    status="completed" if command not in {"debt", "gain", "help"} else "registered",
                    output={"instruction_hash": stable_hash(PonytailPolicy.command_instructions(command, mode))},
                )
        stages = CavekitPolicy.stages_for_action(node, action)
        cavekit_prompt = CavekitPolicy.prompt(stages)
        if cavekit_prompt:
            prompt_parts.append(cavekit_prompt)
        for stage in stages:
            self._record(
                db,
                run=run,
                plugin_name="cavekit",
                plugin_version=CAVEKIT_VERSION,
                source_revision=CAVEKIT_SOURCE_REVISION,
                command=stage,
                mode="v4",
                node_id=node_id,
                phase=phase,
                iteration=iteration,
                action=action,
                execution_unit_id=execution_unit_id,
                status="registered",
                output={"instruction_hash": stable_hash(CavekitPolicy.prompt([stage]))},
            )
        return "\n\n".join(part for part in prompt_parts if part)

    def finish_cavekit_stages(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        iteration: int,
        action: str,
        status: str,
        evidence: dict[str, Any],
        execution_unit_id: str = "",
        error: str = "",
        stages: list[str] | None = None,
    ) -> list[PluginInvocation]:
        if status not in {"completed", "not_applicable", "failed"}:
            raise ValueError("Cavekit stage result must be terminal")
        if status == "completed" and not any(
            evidence.get(key)
            for key in ("step_execution_id", "execution_unit_id", "test_report_ids", "quality_gate_ids")
        ):
            raise ValueError("completed Cavekit stages require persisted execution evidence")
        if status == "not_applicable" and not evidence.get("reason"):
            raise ValueError("not-applicable Cavekit stages require a reason")
        rows: list[PluginInvocation] = []
        selected = CavekitPolicy.stages_for_action(node, action)
        if stages is not None:
            selected = [stage for stage in selected if stage in stages]
        for stage in selected:
            row = self._record(
                db,
                run=run,
                plugin_name="cavekit",
                plugin_version=CAVEKIT_VERSION,
                source_revision=CAVEKIT_SOURCE_REVISION,
                command=stage,
                mode="v4",
                node_id=str(node.get("id") or ""),
                phase=str(node.get("phase") or ""),
                iteration=iteration,
                action=action,
                execution_unit_id=execution_unit_id,
                status="registered",
                output={"instruction_hash": stable_hash(CavekitPolicy.prompt([stage]))},
            )
            rows.append(self._finish(
                db,
                run=run,
                row=row,
                status=status,
                output={**evidence, "stage": stage, "iteration": iteration},
                error=error,
            ))
        db.flush()
        return rows

    def record_result(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        plugin_name: str,
        command: str,
        node_id: str,
        iteration: int,
        status: str,
        output: dict[str, Any],
        action: str = "result",
        execution_unit_id: str = "",
    ) -> PluginInvocation:
        if plugin_name == "ponytail":
            version, revision, mode = PONYTAIL_VERSION, PONYTAIL_SOURCE_REVISION, "full"
        else:
            version, revision, mode = CAVEKIT_VERSION, CAVEKIT_SOURCE_REVISION, "v4"
        return self._record(
            db,
            run=run,
            plugin_name=plugin_name,
            plugin_version=version,
            source_revision=revision,
            command=command,
            mode=mode,
            node_id=node_id,
            phase=run.current_phase,
            iteration=iteration,
            action=action,
            execution_unit_id=execution_unit_id,
            status=status,
            output=output,
        )

    def ensure_mission_coverage(self, db: Session, *, run: WorkflowRun) -> None:
        required = {
            "ponytail": ["activate", "instructions", "review", "audit", "debt", "gain", "help"],
            "cavekit": ["grill", "spec", "research", "review", "build", "check", "backprop", "deepen", "caveman"],
        }
        rows = db.query(PluginInvocation).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        for row in rows:
            if row.plugin_name == "cavekit" and row.status == "registered":
                self._finish(
                    db,
                    run=run,
                    row=row,
                    status="not_applicable",
                    output={
                        "reason": "stage had no valid terminal evidence in this mission",
                        "evidence_type": "mission_coverage",
                    },
                )
        seen = {(row.plugin_name, row.command) for row in rows}
        for plugin_name, commands in required.items():
            for command in commands:
                if (plugin_name, command) in seen:
                    continue
                self.record_result(
                    db,
                    run=run,
                    plugin_name=plugin_name,
                    command=command,
                    node_id=run.current_node or "Quality Governor",
                    iteration=1,
                    status="not_applicable",
                    output={"reason": "mandatory stage had no valid input in this mission"},
                    action="coverage",
                )

    def _record(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        plugin_name: str,
        plugin_version: str,
        source_revision: str,
        command: str,
        mode: str,
        node_id: str,
        phase: str,
        iteration: int,
        action: str,
        execution_unit_id: str,
        status: str,
        output: dict[str, Any],
        error: str = "",
    ) -> PluginInvocation:
        started = time.perf_counter()
        invocation_key = stable_hash(
            {
                "tenant_id": run.tenant_id,
                "run_id": run.id,
                "plugin": plugin_name,
                "version": plugin_version,
                "command": command,
                "node_id": node_id,
                "iteration": iteration,
                "action": action,
                "execution_unit_id": execution_unit_id,
            }
        )
        existing: Optional[PluginInvocation] = (
            db.query(PluginInvocation)
            .filter_by(tenant_id=run.tenant_id, invocation_key=invocation_key)
            .first()
        )
        if existing:
            return existing
        row = PluginInvocation(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            execution_unit_id=execution_unit_id or None,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            source_revision=source_revision,
            command=command,
            mode=mode,
            node_id=node_id,
            phase=phase,
            action=action,
            status=status,
            invocation_key=invocation_key,
            input_hash=stable_hash({"command": command, "mode": mode, "action": action}),
            output_hash=stable_hash(output),
            metadata_json={**output, "iteration": iteration},
            error=error,
            duration_seconds=round(time.perf_counter() - started, 6),
            trace_id=run.trace_id,
        )
        db.add(row)
        emit_event(
            db,
            run.id,
            f"plugin.{plugin_name}.{command}",
            f"{plugin_name}@{plugin_version} {command}: {status}.",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            tool_call_id=row.id,
            status="success" if status in {"completed", "registered", "not_applicable"} else status,
            payload={
                "plugin_invocation_id": row.id,
                "plugin": plugin_name,
                "version": plugin_version,
                "source_revision": source_revision,
                "command": command,
                "mode": mode,
                "status": status,
                "execution_unit_id": execution_unit_id,
            },
        )
        db.flush()
        return row

    @staticmethod
    def _finish(
        db: Session,
        *,
        run: WorkflowRun,
        row: PluginInvocation,
        status: str,
        output: dict[str, Any],
        error: str = "",
    ) -> PluginInvocation:
        if row.status != "registered":
            return row
        row.status = status
        row.metadata_json = {**(row.metadata_json or {}), **output}
        row.output_hash = stable_hash(output)
        row.error = error[:8000]
        emit_event(
            db,
            run.id,
            f"plugin.{row.plugin_name}.{row.command}",
            f"{row.plugin_name}@{row.plugin_version} {row.command}: {status}.",
            node_id=row.node_id,
            phase=row.phase,
            agent_name=row.node_id,
            tool_call_id=row.id,
            status="success" if status in {"completed", "not_applicable"} else status,
            payload={
                "plugin_invocation_id": row.id,
                "plugin": row.plugin_name,
                "version": row.plugin_version,
                "source_revision": row.source_revision,
                "command": row.command,
                "mode": row.mode,
                "status": status,
                "execution_unit_id": row.execution_unit_id or "",
                "evidence_hash": row.output_hash,
            },
        )
        return row
