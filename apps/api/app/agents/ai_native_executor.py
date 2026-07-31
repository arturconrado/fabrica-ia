import hashlib
import json
import re
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.ai_native_context import TenantContextBuilder
from app.agents.ai_native_unit_context import UnitContextBuilder
from app.agents.ai_native_contracts import (
    AgentStepResult,
    ArtifactSectionResult,
    ArtifactOutput,
    ContextBundle,
    ContextPolicy,
    FileOperation,
    FileBatchResult,
    NodeFinalizeResult,
    NodePlanResult,
    OutputUnitDescriptor,
    RiskArtifactStepResult,
    UnitContextView,
    output_strategy_for_node,
    result_contract_for_node,
    stable_hash,
)
from app.agents.segmented_execution import SEGMENTED_PROTOCOL_VERSION, SegmentedExecutionService
from app.core.config import get_settings
from app.core.paths import run_workspace
from app.core.security import safe_join
from app.core.status import FAILED, PENDING, RUNNING, SUCCESS, WAITING_FOR_HUMAN
from app.domain.workflow_transition import TransitionState, WorkflowTransitionEngine, WorkflowTransitionError
from app.events.event_service import emit_event
from app.models import (
    AcceptanceCriterion,
    AgentEvent,
    AgentStepExecution,
    Artifact,
    ContextBuild,
    ExecutionUnit,
    FileChange,
    LearningSignal,
    ModelCall,
    PromptVersion,
    QualityGate,
    Requirement,
    RequirementTrace,
    TestReport,
    WorkflowDefinition,
    WorkflowNodeState,
    WorkflowRun,
    utcnow,
)
from app.plugins import FactoryPluginRuntime
from app.plugins.cavekit import CavekitPolicy
from app.plugins.ponytail import PonytailPolicy
from app.providers.model_gateway import ModelGateway, ModelGatewayError
from app.providers.cost_governor import AIInvocationScope, CostEnvelope, classify_retry
from app.learning.optimization_service import LearningOptimizationService
from app.observability.tracing import trace_span
from app.providers.object_storage import object_storage
from app.quality.ai_native_quality import AINativeQualityEvaluator
from app.sandbox.tool_profiles import NODE_REQUIRED_PROFILES, ToolProfileRunner
from app.service_delivery.capacity import release_workflow_slot
from app.service_delivery.service import DomainError
from app.tools.diff_tools import unified_diff
from app.workflow.condition_evaluator import condition_matches


AI_NATIVE_WORKFLOW_ID = "software_factory_ai_native_v2"


class AINativeExecutionError(RuntimeError):
    pass


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def workspace_owner_for_path(path: str) -> Optional[str]:
    """Return the single discipline allowed to author a v2.14 workspace path."""
    normalized = str(PurePosixPath(path.strip().replace("\\", "/")))
    if not normalized.startswith("generated_app/"):
        return None
    relative = normalized.removeprefix("generated_app/")
    name = PurePosixPath(relative).name
    if (
        relative.startswith("deploy/")
        or relative.startswith(".github/workflows/")
        or name.startswith("Dockerfile")
        or (name.startswith("docker-compose") and name.endswith((".yml", ".yaml")))
    ):
        return "DevOps Engineer"
    if relative.startswith("backend/tests/") or relative.startswith("e2e/"):
        return "QA Engineer"
    if relative.startswith("frontend/tests/") or (
        relative.startswith("frontend/") and (".test." in name or ".spec." in name)
    ):
        return "QA Engineer"
    if relative.startswith("architecture/"):
        return "Architect"
    if relative.startswith(("backend/migrations/", "backend/schemas/")):
        return "Data Architect"
    if relative.startswith("contracts/"):
        return "API Contract Engineer"
    if relative.startswith("security/"):
        return "Security Engineer"
    if relative.startswith(("backend/", "frontend/")) or relative == "README.md":
        return "Engineer"
    return None


def validate_workspace_path_ownership(node_id: str, path: str) -> None:
    owner = workspace_owner_for_path(path)
    if owner != node_id:
        raise AINativeExecutionError(
            f"{node_id} cannot author {path}; bounded owner is {owner or 'none'}"
        )


def qa_failure_owner(reports: list[TestReport]) -> str:
    """Route only clear test-authorship defects back to QA; product failures stay with Engineer."""

    failed = [report for report in reports if report.status != "passed"]
    if not failed:
        return "none"

    def is_test_authorship_defect(report: TestReport) -> bool:
        evidence = f"{report.stdout}\n{report.stderr}".casefold()
        test_command = (
            "generated_app/backend/tests" in report.command
            or report.command.strip() == "npm --prefix generated_app/frontend run test"
        )
        if not test_command:
            return False
        if any(
            marker in evidence
            for marker in (
                "no tests ran",
                "no tests found",
                "no test files found",
                "file or directory not found: generated_app/backend/tests",
            )
        ):
            return True
        owns_error_path = bool(
            re.search(
                r"generated_app/(?:backend/tests/|frontend/(?:tests/|[^\s:]+\.(?:test|spec)\.))",
                evidence,
            )
        )
        return owns_error_path and any(
            marker in evidence
            for marker in ("error collecting", "syntaxerror", "failed to parse", "parse error")
        )

    return "QA Engineer" if all(is_test_authorship_defect(report) for report in failed) else "Engineer"


def node_output_strategy(node: dict[str, Any]) -> str:
    return str(node.get("output_strategy") or output_strategy_for_node(str(node.get("id") or "")))


def apply_unified_patch(original: str, patch: str) -> str:
    """Apply content hunks to one already-authorized path; patch headers never select files."""

    source = original.splitlines(keepends=True)
    lines = patch.splitlines(keepends=True)
    output: list[str] = []
    cursor = 0
    index = 0
    hunks = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(("--- ", "+++ ")) or not line.strip():
            index += 1
            continue
        match = _HUNK_HEADER.match(line.rstrip("\r\n"))
        if not match:
            raise AINativeExecutionError("patch contains data outside a valid unified-diff hunk")
        hunks += 1
        old_start = int(match.group(1))
        old_expected = int(match.group(2) or 1)
        new_expected = int(match.group(4) or 1)
        hunk_start = max(0, old_start - 1)
        if hunk_start < cursor or hunk_start > len(source):
            raise AINativeExecutionError("patch hunk position is outside the current file")
        output.extend(source[cursor:hunk_start])
        cursor = hunk_start
        old_seen = 0
        new_seen = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            hunk_line = lines[index]
            if hunk_line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not hunk_line or hunk_line[0] not in {" ", "+", "-"}:
                raise AINativeExecutionError("patch hunk contains an unsupported line")
            marker = hunk_line[0]
            payload = hunk_line[1:]
            if marker in {" ", "-"}:
                if cursor >= len(source) or source[cursor] != payload:
                    raise AINativeExecutionError("patch context does not match the current file")
                cursor += 1
                old_seen += 1
            if marker in {" ", "+"}:
                output.append(payload)
                new_seen += 1
            index += 1
        if old_seen != old_expected or new_seen != new_expected:
            raise AINativeExecutionError("patch hunk line counts do not match its header")
    if not hunks:
        raise AINativeExecutionError("patch requires at least one unified-diff hunk")
    output.extend(source[cursor:])
    result = "".join(output)
    if len(result) > 200_000:
        raise AINativeExecutionError("patched file exceeds the 200000-character workspace limit")
    return result


class AINativeWorkflowExecutor:
    def __init__(self, *, gateway: Optional[ModelGateway] = None) -> None:
        self.gateway = gateway or ModelGateway()
        self.context_builder = TenantContextBuilder()
        self.tool_runner = ToolProfileRunner()
        self.quality = AINativeQualityEvaluator()
        self.learning = LearningOptimizationService()
        self.segmented = SegmentedExecutionService()
        self.plugins = FactoryPluginRuntime()

    def execute(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        provider: Any,
        max_nodes: Optional[int] = None,
        segmented_finalize_only: bool = False,
    ) -> WorkflowRun:
        with trace_span(
            "workflow.run",
            {
                "asf.run_id": run.id,
                "asf.workflow_id": run.workflow_id,
                "asf.protocol": run.executor_protocol_version,
            },
        ):
            return self._execute(
                db,
                run=run,
                provider=provider,
                max_nodes=max_nodes,
                segmented_finalize_only=segmented_finalize_only,
            )

    def _execute(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        provider: Any,
        max_nodes: Optional[int] = None,
        segmented_finalize_only: bool = False,
    ) -> WorkflowRun:
        if run.workflow_id != AI_NATIVE_WORKFLOW_ID or run.generation_mode != "ai_native_v2":
            raise AINativeExecutionError("AI-native executor only accepts versioned v2 runs")
        definition_query = db.query(WorkflowDefinition).filter_by(
            tenant_id=run.tenant_id,
            workflow_id=AI_NATIVE_WORKFLOW_ID,
        )
        pinned_version = str((run.context_manifest_json or {}).get("workflow_version") or "")
        if pinned_version:
            definition_query = definition_query.filter(WorkflowDefinition.version == pinned_version)
        definition = (
            definition_query
            .order_by(WorkflowDefinition.created_at.desc())
            .first()
        )
        if not definition or not definition.yaml_content:
            raise AINativeExecutionError("Persisted AI-native workflow definition is required")
        production_plugins_active = definition.version in {"2.13.2", "2.14.0"}
        graph = (yaml.safe_load(definition.yaml_content) or {}).get("graph") or {}
        if production_plugins_active:
            self._validate_production_plugins(graph)
        transition_engine = (
            WorkflowTransitionEngine(graph)
            if run.executor_protocol_version == SEGMENTED_PROTOCOL_VERSION
            else None
        )
        nodes = {str(node["id"]): node for node in graph.get("nodes") or []}
        edges = list(graph.get("edges") or [])
        for node_id, node in nodes.items():
            node["allowed_decisions"] = [
                str(edge.get("condition"))
                for edge in edges
                if str(edge.get("from")) == node_id and edge.get("condition") is not True
            ]
        if "Demand Classifier" not in nodes or "Human Approval" not in nodes:
            raise AINativeExecutionError("AI-native workflow is incomplete")

        run.status = RUNNING
        run.provider = "litellm-ai-native-v2"
        run.ai_budget_usd = float(run.ai_budget_usd or get_settings().model_run_budget_usd)
        current = run.current_node if run.current_node in nodes and run.current_node not in {"USER", "Temporal Worker"} else "Demand Classifier"
        iterations: dict[str, int] = self._restored_iterations(db, run)
        resume = (run.context_manifest_json or {}).get("resume") or {}
        if resume.get("node") == current and int(resume.get("iteration") or 0) > iterations.get(current, 0):
            iterations[current] = int(resume["iteration"])
        edge_iterations: dict[str, int] = {}
        restored_edge_iterations = self._restored_edge_iterations(db, run)
        restored_completed_steps = self._restored_completed_step_count(db, run, current)
        transition_state = TransitionState(
            current_node=current,
            total_steps=restored_completed_steps,
            node_iterations={**iterations, current: iterations.get(current, 1)},
            edge_iterations=restored_edge_iterations,
        )
        total_steps = 0
        max_total_steps = int((graph.get("execution") or {}).get("max_total_steps") or get_settings().agent_max_total_steps)

        while current not in {"Human Approval", "FINAL"}:
            total_steps += 1
            if total_steps > max_total_steps:
                return self._fail_run(db, run, "AI-native workflow exceeded its persisted maximum step count")
            node = nodes.get(current)
            if not node or node.get("type") != "agent":
                return self._fail_run(db, run, f"Unsupported executable node: {current}")
            iteration = iterations.get(current, 1)
            run.current_node = current
            run.current_phase = str(node.get("phase") or "")
            run.updated_at = utcnow()
            db.commit()

            result = self._completed_result(db, run, current, iteration)
            if result is None:
                last_error: Optional[Exception] = None
                for attempt in range(1, max(1, get_settings().agent_max_step_attempts) + 1):
                    try:
                        with trace_span(
                            "workflow.node",
                            {
                                "asf.run_id": run.id,
                                "asf.node": current,
                                "asf.iteration": iteration,
                                "asf.attempt": attempt,
                            },
                        ):
                            if (
                                run.executor_protocol_version == SEGMENTED_PROTOCOL_VERSION
                                and node_output_strategy(node) != "atomic"
                            ):
                                result = self._execute_segmented_node(
                                    db,
                                    run=run,
                                    node=node,
                                    workflow_version=definition.version,
                                    iteration=iteration,
                                    attempt=attempt,
                                    mode="finalize" if segmented_finalize_only else "all",
                                )
                            else:
                                result = self._execute_agent_node(
                                    db,
                                    run=run,
                                    node=node,
                                    workflow_version=definition.version,
                                    iteration=iteration,
                                    attempt=attempt,
                                )
                        last_error = None
                        break
                    except Exception as exc:
                        db.rollback()
                        last_error = exc
                        if classify_retry(exc) == "budget_or_isolation":
                            break
                        if attempt < max(1, get_settings().agent_max_step_attempts):
                            settings = get_settings()
                            wait_seconds = 0.0 if settings.runtime_profile.lower() == "test" else max(
                                0.0,
                                float(settings.agent_retry_backoff_seconds) * attempt,
                            )
                            emit_event(
                                db,
                                run.id,
                                "agent.retry_scheduled",
                                f"{current} terá nova tentativa após saída inválida ou falha transitória.",
                                node_id=current,
                                phase=str(node.get("phase") or ""),
                                agent_name=current,
                                status="retrying",
                                payload={
                                    "attempt": attempt,
                                    "next_attempt": attempt + 1,
                                    "wait_seconds": wait_seconds,
                                    "error": str(exc)[:1000],
                                },
                            )
                            db.commit()
                            if wait_seconds:
                                time.sleep(wait_seconds)
                if last_error is not None or result is None:
                    if last_error is not None and "budget" in str(last_error).casefold():
                        return self._pause_for_budget(db, run, f"{current} paused: {last_error}")
                    return self._fail_run(db, run, f"{current} failed: {last_error}")

            decision = result.decision
            required_profiles = NODE_REQUIRED_PROFILES.get(current, [])
            if required_profiles:
                reports = []
                try:
                    for profile in required_profiles:
                        reports.append(self.tool_runner.run(db, run=run, node_id=current, profile_name=profile))
                    for report in reports:
                        db.add(
                            LearningSignal(
                                id=str(uuid.uuid4()),
                                tenant_id=run.tenant_id,
                                run_id=run.id,
                                signal_type="test.profile_completed",
                                source_type="test_report",
                                source_id=report.id,
                                agent_name=current,
                                value=1.0 if report.status == "passed" else -1.0,
                                evidence_json={
                                    "profile": report.command,
                                    "status": report.status,
                                    "passed": report.passed_count,
                                    "failed": report.failed_count,
                                    "sandbox_execution_id": report.sandbox_execution_id,
                                },
                                eligible_for_global=False,
                            )
                        )
                    db.commit()
                    observation_attempt = self._latest_any_step_attempt(db, run, current, iteration) + 1
                    observation = self._execute_agent_node(
                        db,
                        run=run,
                        node=node,
                        workflow_version=definition.version,
                        iteration=iteration,
                        attempt=observation_attempt,
                        observation_only=True,
                        plugin_action=f"observe:{observation_attempt}",
                    )
                    result = observation
                except Exception as exc:
                    db.rollback()
                    if "budget" in str(exc).casefold():
                        return self._pause_for_budget(db, run, f"{current} observation paused: {exc}")
                    return self._fail_run(db, run, f"{current} could not observe allowlisted tool evidence: {exc}")
                tools_passed = all(report.status == "passed" for report in reports)
                if current == "QA Engineer":
                    failure_owner = qa_failure_owner(reports)
                    decision = (
                        "tests_passed"
                        if tools_passed
                        else "tests_invalid"
                        if definition.version == "2.14.0" and failure_owner == "QA Engineer"
                        else "tests_failed"
                    )
                    if production_plugins_active:
                        self.plugins.finish_cavekit_stages(
                            db,
                            run=run,
                            node=node,
                            iteration=iteration,
                            action=f"observe:{observation_attempt}",
                            stages=["backprop"],
                            status="not_applicable" if tools_passed else "completed",
                            evidence={
                                "evidence_type": "sandbox_backpropagation",
                                "reason": (
                                    "no failure to backpropagate"
                                    if tools_passed
                                    else f"real sandbox failure routed to {failure_owner} rework"
                                ),
                                "test_report_ids": [report.id for report in reports],
                                "failed_profiles": [report.command for report in reports if report.status != "passed"],
                            },
                        )
                    if tools_passed:
                        self._build_traceability(db, run)
                else:
                    decision = "passed" if tools_passed else "blocked"
                self._override_step_decision(db, run, current, iteration, decision)
                db.commit()

            if current == "Quality Governor":
                if production_plugins_active:
                    calls_for_gain = db.query(ModelCall).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
                    self.plugins.record_result(
                        db,
                        run=run,
                        plugin_name="ponytail",
                        command="gain",
                        node_id=current,
                        iteration=iteration,
                        status="completed",
                        output={
                            "prompt_tokens": sum(call.prompt_tokens for call in calls_for_gain),
                            "completion_tokens": sum(call.completion_tokens for call in calls_for_gain),
                            "actual_cost_usd": round(sum(call.estimated_cost_usd for call in calls_for_gain), 8),
                            "boundary": "measured run usage only; no upstream savings claim",
                        },
                    )
                    self.plugins.record_result(
                        db,
                        run=run,
                        plugin_name="ponytail",
                        command="help",
                        node_id=current,
                        iteration=iteration,
                        status="completed",
                        output={"manifest_sha256": PonytailPolicy.manifest()["manifest_sha256"]},
                    )
                score, blockers = self.quality.evaluate(db, run=run, package_builder=provider._build_package)
                quality_gates = db.query(QualityGate).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
                for gate in quality_gates:
                    db.add(
                        LearningSignal(
                            id=str(uuid.uuid4()),
                            tenant_id=run.tenant_id,
                            run_id=run.id,
                            signal_type="quality.gate_evaluated",
                            source_type="quality_gate",
                            source_id=gate.id,
                            agent_name="Quality Governor",
                            value=1.0 if gate.status in {"passed", "pass", "approved"} else -1.0,
                            evidence_json={"gate_id": gate.gate_id, "status": gate.status, "score": gate.score},
                            eligible_for_global=False,
                        )
                    )
                db.add(
                    LearningSignal(
                        id=str(uuid.uuid4()),
                        tenant_id=run.tenant_id,
                        run_id=run.id,
                        signal_type="quality.run_evaluated",
                        source_type="workflow_run",
                        source_id=run.id,
                        agent_name="Quality Governor",
                        value=max(-1.0, min(1.0, (float(score) - 50.0) / 50.0)),
                        evidence_json={
                            "hrs": score,
                            "blockers": blockers,
                            "gate_count": len(quality_gates),
                        },
                        eligible_for_global=False,
                    )
                )
                if production_plugins_active:
                    quality_step = (
                        db.query(AgentStepExecution)
                        .filter_by(
                            tenant_id=run.tenant_id,
                            run_id=run.id,
                            node_id=current,
                            iteration=iteration,
                            status="completed",
                        )
                        .order_by(AgentStepExecution.attempt.desc())
                        .first()
                    )
                    self.plugins.finish_cavekit_stages(
                        db,
                        run=run,
                        node={**node, "cavekit_stages": ["deepen"]},
                        iteration=iteration,
                        action="deepen",
                        status="not_applicable" if blockers else "completed",
                        evidence={
                            "evidence_type": "post_gate_deepening",
                            "reason": "quality blockers prevent behavior-preserving deepening" if blockers else "green gates reviewed; no automatic behavior change applied",
                            "step_execution_id": quality_step.id if quality_step else "",
                            "quality_gate_ids": [gate.id for gate in quality_gates],
                            "hrs": score,
                            "blockers": blockers,
                        },
                    )
                    self.plugins.ensure_mission_coverage(db, run=run)
                decision = "blocked" if blockers else "approved_for_homologation"
                self._override_step_decision(db, run, current, iteration, decision)
                db.commit()
                if blockers:
                    return self._fail_run(db, run, f"Deterministic quality gates blocked homologation: {', '.join(blockers)}")
                restored_policies = self.learning.enforce_runtime_rollback(db, run=run)
                if restored_policies:
                    emit_event(
                        db,
                        run.id,
                        "learning.policy_auto_rolled_back",
                        "Regressão crítica detectada; ponteiro de política anterior restaurado.",
                        node_id=current,
                        phase="quality_governance",
                        payload={"restored_policy_ids": restored_policies},
                    )
                    db.commit()
                emit_event(
                    db,
                    run.id,
                    "homologation.ready_for_human",
                    f"HRS provisório {score}; decisão humana obrigatória.",
                    node_id=current,
                    phase="quality_governance",
                    payload={"hrs": score},
                )

            if transition_engine:
                try:
                    transition = transition_engine.transition(transition_state, decision)
                except WorkflowTransitionError as exc:
                    return self._fail_run(db, run, str(exc))
                target = transition.target_node
                transition_state = transition.state
                iterations[target] = transition.target_iteration
            else:
                next_edge = self._next_edge(edges, current, decision)
                if not next_edge:
                    return self._fail_run(db, run, f"No workflow edge matches {current} decision {decision}")
                target = str(next_edge["to"])
                edge_key = f"{current}->{target}"
                if target in iterations and target in {"Engineer", "Code Reviewer", "QA Engineer"}:
                    edge_iterations[edge_key] = edge_iterations.get(edge_key, 0) + 1
                    max_iterations = int(next_edge.get("max_iterations") or 0)
                    if max_iterations and edge_iterations[edge_key] > max_iterations:
                        return self._fail_run(db, run, f"Workflow loop limit exceeded for {edge_key}")
                    iterations[target] = iterations.get(target, 1) + 1
                else:
                    iterations.setdefault(target, 1)
            emit_event(
                db,
                run.id,
                "agent.handoff",
                f"Handoff: {current} → {target}.",
                node_id=target,
                phase=str(nodes.get(target, {}).get("phase") or ""),
                agent_name=target,
                payload={"from_agent": current, "to_agent": target, "decision": decision, "iteration": iterations.get(target, 1)},
            )
            run.current_node = target
            run.current_phase = str(nodes.get(target, {}).get("phase") or "")
            run.updated_at = utcnow()
            db.commit()
            current = target
            if max_nodes is not None and total_steps >= max_nodes and current not in {"Human Approval", "FINAL"}:
                db.refresh(run)
                return run

        if current == "Human Approval":
            with trace_span(
                "human.approval",
                {"asf.run_id": run.id, "asf.node": current, "asf.action": "prepare"},
            ):
                provider._request_human_approval(db, run)
            run.status = WAITING_FOR_HUMAN
            db.commit()
            db.refresh(run)
        return run

    def plan_temporal_segmented_node(self, db: Session, *, run: WorkflowRun) -> dict[str, Any]:
        """Persist only the frozen context, model-generated manifest and unit checkpoints."""

        definition, node = self._segmented_definition_and_node(db, run)
        current_step = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=run.current_node)
            .order_by(AgentStepExecution.iteration.desc(), AgentStepExecution.attempt.desc())
            .first()
        )
        if current_step and current_step.status == "completed":
            units = db.query(ExecutionUnit).filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=run.current_node,
                iteration=current_step.iteration,
                action="execute",
            ).order_by(ExecutionUnit.order_index.asc()).all()
            if units and all(unit.status == "completed" for unit in units):
                return {
                    "run_id": run.id,
                    "node_id": run.current_node,
                    "step_execution_id": current_step.id,
                    "execution_unit_ids": [unit.id for unit in units],
                    "status": "planned",
                }
        if current_step and current_step.status == "failed":
            plan_unit = db.query(ExecutionUnit).filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=run.current_node,
                iteration=current_step.iteration,
                action="plan",
            ).first()
            if not plan_unit or plan_unit.attempt_count >= plan_unit.max_attempts:
                raise AINativeExecutionError("segmented node plan exhausted its persisted retry limit")
            current_step.status = "running"
            current_step.error = ""
            state = db.get(WorkflowNodeState, current_step.workflow_node_state_id)
            if state:
                state.status = RUNNING
                state.summary = ""
            emit_event(
                db,
                run.id,
                "agent.checkpoint_recovered",
                f"{run.current_node} retomou o checkpoint de planejamento sem criar um novo contexto.",
                node_id=run.current_node,
                phase=run.current_phase,
                payload={"step_execution_id": current_step.id, "execution_unit_id": plan_unit.id},
            )
            db.commit()
        iteration = int(current_step.iteration if current_step else self._restored_iterations(db, run).get(run.current_node, 1))
        attempt = int(current_step.attempt if current_step else self._latest_any_step_attempt(db, run, run.current_node, iteration) + 1)
        return self._execute_segmented_node(
            db,
            run=run,
            node=node,
            workflow_version=definition.version,
            iteration=iteration,
            attempt=attempt,
            mode="plan",
        )

    def execute_temporal_output_unit(
        self, db: Session, *, run: WorkflowRun, execution_unit_id: str
    ) -> dict[str, Any]:
        """Execute exactly one persisted output unit; Temporal owns retries and ordering."""

        unit = db.query(ExecutionUnit).filter_by(
            id=execution_unit_id, tenant_id=run.tenant_id, run_id=run.id
        ).first()
        if not unit or unit.action != "execute" or unit.node_id != run.current_node:
            raise AINativeExecutionError("execution unit is outside the active tenant/run/node checkpoint")
        if unit.status == "completed":
            return {
                "run_id": run.id,
                "node_id": unit.node_id,
                "execution_unit_id": unit.id,
                "status": unit.status,
                "output_hash": unit.output_hash,
                "model_call_id": unit.model_call_id,
            }
        definition, node = self._segmented_definition_and_node(db, run)
        step = db.get(AgentStepExecution, unit.step_execution_id) if unit.step_execution_id else None
        if unit.status == "failed" and unit.attempt_count >= unit.max_attempts:
            raise AINativeExecutionError(f"execution unit {unit.unit_key} exhausted its persisted retry limit")
        if step and step.status == "failed":
            step.status = "running"
            step.error = ""
            state = db.get(WorkflowNodeState, step.workflow_node_state_id)
            if state:
                state.status = RUNNING
                state.summary = ""
            emit_event(
                db,
                run.id,
                "agent.checkpoint_recovered",
                f"{unit.node_id}/{unit.unit_key} retomou o contexto congelado após uma falha recuperável.",
                node_id=unit.node_id,
                phase=unit.phase,
                payload={"step_execution_id": step.id, "execution_unit_id": unit.id},
            )
            db.commit()
        attempt = int(step.attempt if step else self._latest_any_step_attempt(db, run, unit.node_id, unit.iteration) + 1)
        return self._execute_segmented_node(
            db,
            run=run,
            node=node,
            workflow_version=definition.version,
            iteration=unit.iteration,
            attempt=attempt,
            mode="unit",
            execution_unit_id=unit.id,
        )

    def _segmented_definition_and_node(
        self, db: Session, run: WorkflowRun
    ) -> tuple[WorkflowDefinition, dict[str, Any]]:
        definition_query = db.query(WorkflowDefinition).filter_by(
            tenant_id=run.tenant_id, workflow_id=run.workflow_id
        )
        pinned = str((run.context_manifest_json or {}).get("workflow_version") or "")
        if pinned:
            definition_query = definition_query.filter(WorkflowDefinition.version == pinned)
        definition = definition_query.order_by(WorkflowDefinition.created_at.desc()).first()
        if not definition or not definition.yaml_content:
            raise AINativeExecutionError("persisted segmented workflow definition is missing")
        graph = (yaml.safe_load(definition.yaml_content) or {}).get("graph") or {}
        if definition.version in {"2.13.2", "2.14.0"}:
            self._validate_production_plugins(graph)
        node = next(
            (dict(item) for item in graph.get("nodes") or [] if str(item.get("id")) == run.current_node),
            None,
        )
        if not node or node_output_strategy(node) == "atomic":
            raise AINativeExecutionError("active node does not use segmented output")
        node["allowed_decisions"] = [
            str(edge.get("condition"))
            for edge in graph.get("edges") or []
            if str(edge.get("from")) == run.current_node and edge.get("condition") is not True
        ]
        return definition, node

    def _validate_production_plugins(self, graph: dict[str, Any]) -> None:
        settings = get_settings()
        if not settings.production_plugins_enabled:
            raise AINativeExecutionError("production plugins are disabled for a pinned production-policy run")
        if not settings.plugin_fail_closed:
            raise AINativeExecutionError("pinned production policies require fail-closed plugin execution")
        try:
            self.plugins.validate_execution_manifest(graph.get("execution") or {})
        except ValueError as exc:
            raise AINativeExecutionError(str(exc)) from exc

    def _execute_segmented_node(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        workflow_version: str,
        iteration: int,
        attempt: int,
        mode: str = "all",
        execution_unit_id: str = "",
    ) -> Any:
        if mode not in {"all", "plan", "unit", "finalize"}:
            raise AINativeExecutionError(f"unsupported segmented execution mode {mode}")
        node_id = str(node["id"])
        phase = str(node.get("phase") or "")
        strategy = node_output_strategy(node)
        context_policy = ContextPolicy.model_validate(node.get("context_policy") or {})
        step = (
            db.query(AgentStepExecution)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                iteration=iteration,
                status="running",
            )
            .order_by(AgentStepExecution.attempt.desc())
            .first()
        )
        new_checkpoint = step is None
        if step:
            state = db.get(WorkflowNodeState, step.workflow_node_state_id)
            if not state:
                raise AINativeExecutionError("segmented checkpoint lost its workflow node state")
            prompt = db.get(PromptVersion, step.prompt_version_id) if step.prompt_version_id else None
            prompt = prompt or self._prompt_version(db, node=node, workflow_version=workflow_version)
            frozen_context = (step.output_manifest_json or {}).get("context_bundle")
            context = (
                ContextBundle.model_validate(frozen_context)
                if frozen_context
                else self.context_builder.build(
                    db,
                    run=run,
                    node_id=node_id,
                    policy=context_policy,
                )
            )
            context_build = db.query(ContextBuild).filter_by(
                tenant_id=run.tenant_id, step_execution_id=step.id
            ).first()
        else:
            state = WorkflowNodeState(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                phase=phase,
                agent_name=node_id,
                status=RUNNING,
                iteration=iteration,
                max_iterations=max(1, int(node.get("max_iterations") or 1)),
            )
            db.add(state)
            db.flush()
            context = self.context_builder.build(db, run=run, node_id=node_id, policy=context_policy)
            prompt = self._prompt_version(db, node=node, workflow_version=workflow_version)
            step = AgentStepExecution(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                workflow_node_state_id=state.id,
                prompt_version_id=prompt.id,
                node_id=node_id,
                phase=phase,
                iteration=iteration,
                attempt=attempt,
                status="running",
                input_hash=context.input_hash,
                input_manifest_json=self._context_manifest(context),
                output_manifest_json={"context_bundle": context.model_dump(mode="json")},
                output_refs_json=[],
            )
            db.add(step)
            context_build = None
        if context_build is None:
            context_build = ContextBuild(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_execution_id=step.id,
                node_id=node_id,
                policy_version=context.policy_version,
                input_budget_tokens=context.input_budget_tokens,
                estimated_input_tokens=context.estimated_input_tokens,
                selected_tokens=context.estimated_input_tokens,
                discarded_tokens=context.discarded_tokens,
                selected_references_json=[
                    {
                        "kind": reference.kind,
                        "ref_id": reference.ref_id,
                        "label": reference.label,
                        "checksum": reference.checksum,
                        "estimated_tokens": max(1, len(reference.content.encode("utf-8")) // 4),
                        "reason": context.selection_reasons.get(reference.ref_id, "selected by policy"),
                    }
                    for reference in context.references
                ],
                discarded_references_json=context.discarded_references,
                selection_reasons_json=context.selection_reasons,
            )
            db.add(context_build)
        if new_checkpoint:
            emit_event(
                db,
                run.id,
                "agent.sop_started",
                f"{node_id} iniciou execução {strategy} com checkpoints por unidade.",
                node_id=node_id,
                phase=phase,
                agent_name=node_id,
                payload={"iteration": iteration, "attempt": attempt, "executor_protocol_version": SEGMENTED_PROTOCOL_VERSION},
            )
        db.flush()
        output_refs: list[str] = []
        final_result: Optional[NodeFinalizeResult] = None
        cavekit_actions: list[tuple[str, str]] = []
        try:
            plan_descriptor = OutputUnitDescriptor(
                key="node-plan",
                unit_type="atomic",
                targets=[],
                order=0,
                output_budget_tokens=min(4000, int(node.get("max_output_tokens") or 4000)),
            )
            plan_unit = self.segmented.get_or_create_unit(
                db,
                run=run,
                node_state=state,
                step=step,
                node_id=node_id,
                phase=phase,
                iteration=iteration,
                descriptor=plan_descriptor,
                strategy=strategy,
                action="plan",
                trace_id=run.trace_id,
            )
            plan_context = self._prepare_unit_context(
                db,
                run=run,
                context=context,
                policy=context_policy,
                unit=plan_unit,
                action="plan",
            )
            plan_plugin_action = f"plan:{attempt}"
            plan_plugin_prompt = self.plugins.prompt_for_node(
                db,
                run=run,
                node=node,
                iteration=iteration,
                action=plan_plugin_action,
                execution_unit_id=plan_unit.id,
            )
            cavekit_actions.append((plan_plugin_action, plan_unit.id))
            if plan_unit.status == "completed":
                plan = NodePlanResult.model_validate(plan_unit.output_json)
            else:
                plan_system = (
                    f"{prompt.system_prompt}\n\n"
                    "Never reveal chain-of-thought, credentials, commands, or paths outside generated_app/. Use only "
                    "supplied ContextReference ref_id values as citations. Plan this node using the "
                    "segmented-output-v1 protocol. Return only a short NodePlanResult; do not "
                    "generate artifact prose or source code yet. Use artifact_section units for bounded document sections, "
                    "file_batch units for at most four full files, and exactly one final finalize unit. Dependencies must "
                    "reference earlier unit keys. Engineer must manifest every required runnable full-stack path before writing."
                    f"{self._minimal_solution_guardrail(node) if not node.get('ponytail_enabled') else ''}"
                )
                if node.get("ponytail_enabled") and node_id == "Engineer":
                    plan_system += (
                        " Under the v2.13.2 Cavekit contract, every file_batch must cite requirement_refs and invariant_refs; "
                        "test batches must also name exact verification_tests."
                    )
                if plan_plugin_prompt:
                    plan_system = f"{plan_system}\n\n{plan_plugin_prompt}"
                plan_payload, plan_call_id = self._invoke_segmented_unit(
                    db,
                    run=run,
                    node=node,
                    state=state,
                    prompt=prompt,
                    context=context,
                    unit_context=plan_context,
                    unit=plan_unit,
                    response_contract=NodePlanResult,
                    system_prompt=plan_system,
                    user_payload={
                        "unit_context": plan_context.model_dump(mode="json"),
                        "strategy": strategy,
                        "declared_outputs": node.get("outputs") or [],
                    },
                    workflow_version=workflow_version,
                )
                plan = NodePlanResult.model_validate(plan_payload)
                self._validate_segmented_plan(node=node, strategy=strategy, plan=plan)
                self.segmented.complete_unit(
                    db, run=run, unit=plan_unit, output=plan.model_dump(mode="json"), model_call_id=plan_call_id
                )
                plan_call = db.get(ModelCall, plan_call_id)
                context_build.ai_invocation_id = plan_call.ai_invocation_id if plan_call else None
                db.commit()

            self._validate_segmented_plan(node=node, strategy=strategy, plan=plan)
            self._validate_unit_citations(plan_context.references, plan.citations)
            self.plugins.finish_cavekit_stages(
                db,
                run=run,
                node=node,
                iteration=iteration,
                action=plan_plugin_action,
                execution_unit_id=plan_unit.id,
                status="completed",
                evidence={
                    "evidence_type": "validated_segmented_plan",
                    "execution_unit_id": plan_unit.id,
                    "model_call_id": str(plan_unit.model_call_id or ""),
                    "output_hash": plan_unit.output_hash,
                    "citations": plan.citations,
                },
            )
            step.output_manifest_json = {
                **(step.output_manifest_json or {}),
                "context_bundle": context.model_dump(mode="json"),
                "node_plan": plan.model_dump(mode="json"),
                "executor_protocol_version": SEGMENTED_PROTOCOL_VERSION,
            }
            units = self.segmented.persist_plan(
                db,
                run=run,
                node_state=state,
                step=step,
                node_id=node_id,
                phase=phase,
                iteration=iteration,
                plan=plan,
                strategy=strategy,
                trace_id=run.trace_id,
            )
            db.commit()
            if mode == "plan":
                return {
                    "run_id": run.id,
                    "node_id": node_id,
                    "step_execution_id": step.id,
                    "execution_unit_ids": [unit.id for unit in units],
                    "status": "planned",
                }
            selected_units = units
            if mode == "unit":
                selected_units = [unit for unit in units if unit.id == execution_unit_id]
                if len(selected_units) != 1:
                    raise AINativeExecutionError("requested execution unit is not part of the persisted node plan")
            if mode == "finalize":
                pending = [unit.unit_key for unit in units if unit.status != "completed"]
                if pending:
                    raise AINativeExecutionError(f"segmented node cannot finalize with pending units: {pending}")
            for unit in selected_units:
                unit_action = "finalize" if unit.unit_type == "finalize" else "execute"
                unit_plugin_action = f"{unit_action}:{attempt}"
                unit_context = self._prepare_unit_context(
                    db,
                    run=run,
                    context=context,
                    policy=context_policy,
                    unit=unit,
                    action=unit_action,
                    plan_summary=plan.summary,
                )
                unit_plugin_prompt = self.plugins.prompt_for_node(
                    db,
                    run=run,
                    node=node,
                    iteration=iteration,
                    action=unit_plugin_action,
                    execution_unit_id=unit.id,
                )
                cavekit_actions.append((unit_plugin_action, unit.id))
                if unit.status == "completed":
                    parsed = dict(unit.output_json or {})
                    model_call_id = str(unit.model_call_id or "")
                else:
                    if unit.unit_type == "artifact_section":
                        contract = ArtifactSectionResult
                    elif unit.unit_type == "file_batch":
                        contract = FileBatchResult
                    elif unit.unit_type == "finalize":
                        contract = NodeFinalizeResult
                    else:
                        raise AINativeExecutionError(f"unsupported segmented unit type {unit.unit_type}")
                    unit_system = (
                        f"{prompt.system_prompt}\n\n"
                        "Never reveal chain-of-thought, credentials, shell commands, or paths outside generated_app/. "
                        "Use only supplied ContextReference ref_id values as citations. "
                        "Execute exactly one output unit described by the user payload from the persisted plan. "
                        "Do not regenerate other units. Return only the exact unit response schema."
                        f"{self._minimal_solution_guardrail(node) if not node.get('ponytail_enabled') else ''}"
                    )
                    if unit_plugin_prompt:
                        unit_system = f"{unit_system}\n\n{unit_plugin_prompt}"
                    parsed, model_call_id = self._invoke_segmented_unit(
                        db,
                        run=run,
                        node=node,
                        state=state,
                        prompt=prompt,
                        context=context,
                        unit_context=unit_context,
                        unit=unit,
                        response_contract=contract,
                        system_prompt=unit_system,
                        user_payload={
                            "unit": {
                                "key": unit.unit_key,
                                "type": unit.unit_type,
                                "targets": unit.targets_json,
                                "dependencies": unit.dependencies_json,
                                "order": unit.order_index,
                                "requirement_refs": (unit.context_manifest_json or {}).get("requirement_refs", []),
                                "invariant_refs": (unit.context_manifest_json or {}).get("invariant_refs", []),
                                "verification_tests": (unit.context_manifest_json or {}).get("verification_tests", []),
                            },
                            "unit_context": unit_context.model_dump(mode="json"),
                            "plan_summary": plan.summary,
                        },
                        workflow_version=workflow_version,
                    )

                if unit.unit_type == "artifact_section":
                    section = ArtifactSectionResult.model_validate(parsed)
                    self._validate_unit_citations(unit_context.references, section.citations)
                    if section.artifact_name not in set(unit.targets_json or []):
                        raise AINativeExecutionError(
                            f"unit {unit.unit_key} produced undeclared artifact {section.artifact_name}"
                        )
                    fragment = self.segmented.persist_artifact_fragment(
                        db, run=run, unit=unit, result=section, model_call_id=model_call_id
                    )
                    output_refs.append(f"artifact_fragment:{fragment.id}")
                    self.segmented.complete_unit(
                        db, run=run, unit=unit, output=section.model_dump(mode="json"), model_call_id=model_call_id
                    )
                elif unit.unit_type == "file_batch":
                    batch = FileBatchResult.model_validate(parsed)
                    self._validate_unit_citations(unit_context.references, batch.citations)
                    paths = [operation.path for operation in batch.operations]
                    if set(paths) != set(unit.targets_json or []):
                        raise AINativeExecutionError(
                            f"unit {unit.unit_key} file operations differ from its persisted manifest"
                        )
                    for operation in batch.operations:
                        existing_change = (
                            db.query(FileChange)
                            .filter_by(
                                tenant_id=run.tenant_id,
                                run_id=run.id,
                                file_path=operation.path,
                                model_call_id=model_call_id,
                            )
                            .first()
                        )
                        change = existing_change or self._persist_file(
                            db, run, node_id, operation, step.id, model_call_id
                        )
                        change.spec_refs_json = list(
                            dict.fromkeys(
                                [
                                    *(unit.context_manifest_json or {}).get("requirement_refs", []),
                                    *(unit.context_manifest_json or {}).get("invariant_refs", []),
                                    *(unit.context_manifest_json or {}).get("verification_tests", []),
                                ]
                            )
                        )
                        output_refs.append(change.file_path)
                    self.segmented.complete_unit(
                        db, run=run, unit=unit, output=batch.model_dump(mode="json"), model_call_id=model_call_id
                    )
                elif unit.unit_type == "finalize":
                    final_result = NodeFinalizeResult.model_validate(parsed)
                    self.segmented.complete_unit(
                        db, run=run, unit=unit, output=final_result.model_dump(mode="json"), model_call_id=model_call_id
                    )
                self.plugins.finish_cavekit_stages(
                    db,
                    run=run,
                    node=node,
                    iteration=iteration,
                    action=unit_plugin_action,
                    execution_unit_id=unit.id,
                    status="completed",
                    evidence={
                        "evidence_type": "validated_execution_unit",
                        "execution_unit_id": unit.id,
                        "model_call_id": model_call_id,
                        "output_hash": unit.output_hash,
                        "output_refs": list(dict.fromkeys(output_refs)),
                        "unit_type": unit.unit_type,
                    },
                )
                db.commit()

            if mode == "unit":
                completed_unit = selected_units[0]
                return {
                    "run_id": run.id,
                    "node_id": node_id,
                    "execution_unit_id": completed_unit.id,
                    "status": completed_unit.status,
                    "output_hash": completed_unit.output_hash,
                    "model_call_id": completed_unit.model_call_id,
                }

            if mode == "finalize":
                final_unit = next(unit for unit in units if unit.unit_type == "finalize")
                final_result = NodeFinalizeResult.model_validate(final_unit.output_json)

            for artifact_name in node.get("outputs") or []:
                fragment_count = (
                    db.query(ExecutionUnit)
                    .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, iteration=iteration, unit_type="artifact_section")
                    .filter(ExecutionUnit.targets_json.is_not(None))
                    .count()
                )
                if fragment_count and any(
                    artifact_name in (unit.targets_json or []) for unit in units if unit.unit_type == "artifact_section"
                ):
                    artifact = self.segmented.assemble_artifact(
                        db,
                        run=run,
                        node_id=node_id,
                        iteration=iteration,
                        artifact_name=artifact_name,
                        step_execution_id=step.id,
                    )
                    output_refs.append(artifact.name)
            if not final_result:
                raise AINativeExecutionError(f"{node_id} did not produce its required final unit")
            allowed_decisions = set(node.get("allowed_decisions") or [])
            if allowed_decisions and final_result.decision not in allowed_decisions:
                raise AINativeExecutionError(
                    f"{node_id} decision {final_result.decision!r} is not allowed; expected {sorted(allowed_decisions)}"
                )
        except Exception as exc:
            for selected_unit in selected_units:
                if selected_unit.status == "running":
                    self.segmented.fail_unit(db, run=run, unit=selected_unit, error=exc)
            step.status = "failed"
            step.error = str(exc)[:8000]
            step.finished_at = utcnow()
            state.status = FAILED
            state.summary = step.error
            state.finished_at = utcnow()
            for cavekit_action, cavekit_unit_id in cavekit_actions:
                self.plugins.finish_cavekit_stages(
                    db,
                    run=run,
                    node=node,
                    iteration=iteration,
                    action=cavekit_action,
                    execution_unit_id=cavekit_unit_id,
                    status="failed",
                    evidence={
                        "evidence_type": "segmented_execution_failure",
                        "execution_unit_id": cavekit_unit_id,
                        "step_execution_id": step.id,
                        "error_class": type(exc).__name__,
                    },
                    error=str(exc),
                )
            emit_event(
                db,
                run.id,
                "agent.sop_failed",
                f"{node_id} segmented output failed: {str(exc)[:1000]}",
                node_id=node_id,
                phase=phase,
                agent_name=node_id,
                status=FAILED,
                payload={"iteration": iteration, "attempt": attempt, "step_execution_id": step.id},
            )
            db.commit()
            raise

        result = AgentStepResult(
            status="blocked" if final_result.decision == "blocked" else "success",
            decision=final_result.decision,
            summary=final_result.summary,
            risks=final_result.risks,
            citations=[],
            handoff=final_result.handoff,
            confidence=final_result.confidence,
        )
        final_unit = next(unit for unit in units if unit.unit_type == "finalize")
        step.model_call_id = final_unit.model_call_id
        if node_id == "Engineer" and node.get("ponytail_enabled"):
            debt = self._persist_ponytail_debt(
                db,
                run=run,
                step=step,
                model_call_id=str(final_unit.model_call_id or ""),
            )
            output_refs.append(debt.name)
        step.status = "completed" if result.status == "success" else result.status
        step.decision = result.decision
        step.output_hash = result.output_hash()
        step.output_manifest_json = result.model_dump(mode="json")
        step.output_refs_json = list(dict.fromkeys([*output_refs, *final_result.produced_refs]))
        step.finished_at = utcnow()
        state.status = SUCCESS if result.status == "success" else result.status
        state.summary = result.summary
        state.payload_json = {
            "decision": result.decision,
            "confidence": result.confidence,
            "executor_protocol_version": SEGMENTED_PROTOCOL_VERSION,
            "execution_units": [unit.id for unit in units],
            "output_refs": step.output_refs_json,
        }
        state.finished_at = utcnow()
        emit_event(
            db,
            run.id,
            "agent.sop_completed",
            f"{node_id}: {result.summary}",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            status=state.status,
            model_call_id=str(step.model_call_id or ""),
            payload={
                "decision": result.decision,
                "executor_protocol_version": SEGMENTED_PROTOCOL_VERSION,
                "execution_units": [unit.id for unit in units],
                "step_execution_id": step.id,
            },
        )
        db.commit()
        return result

    def _invoke_segmented_unit(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        state: WorkflowNodeState,
        prompt: PromptVersion,
        context: ContextBundle,
        unit_context: UnitContextView,
        unit: ExecutionUnit,
        response_contract: type,
        system_prompt: str,
        user_payload: dict[str, Any],
        workflow_version: str,
    ) -> tuple[dict[str, Any], str]:
        with trace_span(
            "output.unit",
            {
                "asf.run_id": run.id,
                "asf.node": unit.node_id,
                "asf.execution_unit_id": unit.id,
                "asf.unit_key": unit.unit_key,
                "asf.iteration": unit.iteration,
            },
        ):
            return self._invoke_segmented_unit_inner(
                db,
                run=run,
                node=node,
                state=state,
                prompt=prompt,
                context=context,
                unit_context=unit_context,
                unit=unit,
                response_contract=response_contract,
                system_prompt=system_prompt,
                user_payload=user_payload,
                workflow_version=workflow_version,
            )

    def _invoke_segmented_unit_inner(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        state: WorkflowNodeState,
        prompt: PromptVersion,
        context: ContextBundle,
        unit_context: UnitContextView,
        unit: ExecutionUnit,
        response_contract: type,
        system_prompt: str,
        user_payload: dict[str, Any],
        workflow_version: str,
    ) -> tuple[dict[str, Any], str]:
        repair_payload: Optional[dict[str, Any]] = None
        while unit.attempt_count < unit.max_attempts:
            self.segmented.start_unit(db, run=run, unit=unit)
            db.commit()
            try:
                response = self.gateway.call(
                    db=db,
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    agent_name=str(node["id"]),
                    model_role=self._segmented_model_role(node, unit),
                    max_output_tokens=unit.output_budget_tokens,
                    cache_scope="global_static" if unit.attempt_count == 1 else "none",
                    routing_policy_version=workflow_version,
                    workflow_node_state_id=state.id,
                    execution_unit_id=unit.id,
                    prompt_version_id=prompt.id,
                    trace_id=run.trace_id,
                    input_hash=stable_hash({"unit": unit.input_hash, "context": unit_context.input_hash, "repair": repair_payload}),
                    context_refs=[reference.ref_id for reference in unit_context.references],
                    messages=[
                        {"role": "system", "content": system_prompt if repair_payload is None else "Repair the supplied JSON only. Return one complete schema-valid object without adding facts."},
                        {"role": "user", "content": json.dumps(repair_payload or user_payload, ensure_ascii=False, default=str)},
                    ],
                    response_schema=response_contract.model_json_schema(),
                    invocation_scope=AIInvocationScope(
                        scope_type="factory_run",
                        scope_id=run.id,
                        correlation_id=run.trace_id or run.id,
                        policy_version=workflow_version,
                        invocation_id=stable_hash(
                            {
                                "tenant_id": run.tenant_id,
                                "run_id": run.id,
                                "node_id": unit.node_id,
                                "iteration": unit.iteration,
                                "unit_key": unit.unit_key,
                                "action": unit.action,
                            }
                        ),
                        routing_reason="segmented_output_unit",
                        retry_classification="schema_repair" if repair_payload else "initial",
                        attempt_number=unit.attempt_count,
                        envelope=CostEnvelope(
                            soft_budget_usd=round(float(run.ai_budget_usd or 15.0) * 0.8, 4),
                            hard_budget_usd=float(run.ai_budget_usd or 15.0),
                            reserved_budget_usd=float(node.get("reserved_budget_usd") or 0.0),
                        ),
                        metadata={"node_id": unit.node_id, "iteration": unit.iteration, "execution_unit_id": unit.id},
                    ),
                )
            except ModelGatewayError as exc:
                call = db.get(ModelCall, exc.call_id) if exc.call_id else None
                response_json = dict(call.response_json or {}) if call else {}
                finish_reason = str(response_json.get("finish_reason") or "")
                raw = str(response_json.get("raw") or "")
                if finish_reason == "length" and raw and unit.continuation_count < unit.max_continuations:
                    self.segmented.continue_truncated_unit(db, run=run, unit=unit)
                    repair_payload = {"incomplete_response": raw, "instruction": "Continue this unit and return one complete replacement object."}
                    db.commit()
                    continue
                if classify_retry(exc) == "schema_repair" and raw and unit.attempt_count < unit.max_attempts:
                    unit.status = "pending"
                    repair_payload = {"invalid_response": raw, "validation_error": str(exc)[:2000]}
                    db.commit()
                    continue
                self.segmented.fail_unit(db, run=run, unit=unit, error=exc)
                db.commit()
                raise
            content = response.get("content") or {}
            finish_reason = str(content.get("finish_reason") or "")
            if finish_reason == "length":
                self.segmented.continue_truncated_unit(db, run=run, unit=unit)
                repair_payload = {
                    "incomplete_response": str(content.get("raw") or ""),
                    "instruction": "Continue this unit and return one complete replacement object.",
                }
                db.commit()
                continue
            parsed = content.get("parsed")
            if not isinstance(parsed, dict):
                error = AINativeExecutionError(f"unit {unit.unit_key} returned a non-object response")
                self.segmented.fail_unit(db, run=run, unit=unit, error=error)
                db.commit()
                raise error
            return parsed, str(response["id"])
        raise AINativeExecutionError(f"unit {unit.unit_key} exhausted its retry limit")

    @staticmethod
    def _validate_segmented_plan(*, node: dict[str, Any], strategy: str, plan: NodePlanResult) -> None:
        node_id = str(node["id"])
        artifact_targets = {
            target for unit in plan.units if unit.unit_type == "artifact_section" for target in unit.targets
        }
        file_targets = {target for unit in plan.units if unit.unit_type == "file_batch" for target in unit.targets}
        expected_artifacts = set(node.get("outputs") or [])
        if not expected_artifacts.issubset(artifact_targets):
            raise AINativeExecutionError(
                f"{node_id} segmented plan omitted declared artifacts: {sorted(expected_artifacts - artifact_targets)}"
            )
        if strategy == "segmented_artifact" and file_targets:
            raise AINativeExecutionError(f"{node_id} cannot plan workspace mutations")
        if strategy == "segmented_workspace":
            if any(not path.startswith("generated_app/") for path in file_targets):
                raise AINativeExecutionError("Engineer manifest contains paths outside generated_app/")
            if node.get("workspace_ownership_enforced"):
                for path in file_targets:
                    validate_workspace_path_ownership(node_id, path)
            if node.get("ponytail_enabled"):
                file_units = [unit for unit in plan.units if unit.unit_type == "file_batch"]
                missing_refs = [
                    unit.key
                    for unit in file_units
                    if not unit.requirement_refs or not unit.invariant_refs
                ]
                if missing_refs:
                    raise AINativeExecutionError(
                        f"Engineer file batches must cite requirement and invariant refs: {missing_refs}"
                    )
                test_units = [
                    unit
                    for unit in file_units
                    if any("test" in target.casefold() for target in unit.targets)
                ]
                if (
                    not node.get("qa_owns_tests")
                    and (not test_units or any(not unit.verification_tests for unit in test_units))
                ):
                    raise AINativeExecutionError(
                        "Engineer test batches require exact named verification_tests under the Cavekit contract"
                    )
            required_paths = {
                "generated_app/backend/app/main.py",
                "generated_app/frontend/package.json",
                "generated_app/frontend/app/page.tsx",
                "generated_app/README.md",
            }
            missing = required_paths.difference(file_targets)
            backend_test_missing = (
                not node.get("qa_owns_tests")
                and not any(path.startswith("generated_app/backend/tests/test_") for path in file_targets)
            )
            if missing or backend_test_missing:
                detail = sorted(missing | ({"generated_app/backend/tests/test_<feature>.py"} if backend_test_missing else set()))
                raise AINativeExecutionError(f"Engineer file manifest is incomplete: {detail}")

    @staticmethod
    def _validate_unit_citations(references: list[Any], citations: list[str]) -> None:
        invalid = set(citations).difference(reference.ref_id for reference in references)
        if invalid:
            raise AINativeExecutionError(f"segmented unit referenced context that was not supplied: {sorted(invalid)}")

    def _prepare_unit_context(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        context: ContextBundle,
        policy: ContextPolicy,
        unit: ExecutionUnit,
        action: str,
        plan_summary: str = "",
    ) -> UnitContextView:
        rows = (
            db.query(ExecutionUnit)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=unit.node_id,
                iteration=unit.iteration,
                status="completed",
            )
            .order_by(ExecutionUnit.order_index.asc())
            .all()
        )
        dependency_keys = set(unit.dependencies_json or [])

        def summarize(row: ExecutionUnit) -> dict[str, Any]:
            return {
                "unit_key": row.unit_key,
                "unit_type": row.unit_type,
                "targets": list(row.targets_json or []),
                "output_hash": row.output_hash,
                "output": dict(row.output_json or {}),
            }

        dependencies = [summarize(row) for row in rows if row.unit_key in dependency_keys]
        completed = [summarize(row) for row in rows if row.id != unit.id and row.action == "execute"]
        view = UnitContextBuilder().build(
            context=context,
            policy=policy,
            unit=unit,
            action=action,
            plan_summary=plan_summary,
            dependency_outputs=dependencies,
            completed_outputs=completed,
        )
        if unit.context_hash and unit.context_hash != view.input_hash:
            raise AINativeExecutionError(
                f"execution unit {unit.unit_key} context changed after its durable checkpoint"
            )
        first_compaction = not unit.context_hash
        unit.context_hash = view.input_hash
        unit.context_manifest_json = {
            **(unit.context_manifest_json or {}),
            "version": view.version,
            "mode": view.mode,
            "action": view.action,
            "reference_manifest": [
                {
                    "kind": reference.kind,
                    "ref_id": reference.ref_id,
                    "label": reference.label,
                    "checksum": reference.checksum,
                    "reason": view.selection_reasons.get(reference.ref_id, "selected for unit"),
                }
                for reference in view.references
            ],
            "dependency_units": [item["unit_key"] for item in view.dependency_outputs],
            "source_context_hash": view.source_context_hash,
        }
        unit.input_budget_tokens = view.input_budget_tokens
        unit.estimated_input_tokens = view.estimated_input_tokens
        unit.source_input_tokens = view.source_input_tokens
        unit.saved_input_tokens = view.saved_input_tokens
        unit.optimization_policy_version = policy.version if view.mode == "compact" else ""
        if first_compaction and view.mode == "compact":
            emit_event(
                db,
                run.id,
                "context.unit_compacted",
                f"Contexto de {unit.unit_key} reduzido deterministicamente para a unidade.",
                node_id=unit.node_id,
                phase=unit.phase,
                agent_name=unit.node_id,
                payload={
                    "execution_unit_id": unit.id,
                    "policy_version": policy.version,
                    "source_input_tokens": view.source_input_tokens,
                    "estimated_input_tokens": view.estimated_input_tokens,
                    "saved_input_tokens": view.saved_input_tokens,
                    "reference_count": len(view.references),
                },
            )
        db.flush()
        return view

    @staticmethod
    def _segmented_model_role(node: dict[str, Any], unit: ExecutionUnit) -> str:
        if unit.action == "plan":
            return str(node.get("plan_model_role") or node.get("model_role") or "default")
        if unit.unit_type == "finalize":
            return str(node.get("finalize_model_role") or node.get("model_role") or "default")
        return str(node.get("model_role") or "default")

    @staticmethod
    def _minimal_solution_guardrail(node: dict[str, Any]) -> str:
        mode, _commands, prompt = PonytailPolicy.prompt_for_node(node)
        if mode != "off" and prompt:
            return f"\n\n{prompt}"
        if not bool(node.get("minimal_solution_policy")):
            return ""
        return (
            " Before creating anything, inspect the supplied scaffold and evidence. Prefer reuse in this order: "
            "existing code and artifacts, standard library, native platform capabilities, then already-installed "
            "dependencies. Add only the minimum sufficient implementation. Never use minimalism to omit an explicit "
            "requirement, trust-boundary validation, security control, accessibility behavior, error handling, test or evidence."
        )

    def _execute_agent_node(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        workflow_version: str,
        iteration: int,
        attempt: int = 1,
        observation_only: bool = False,
        plugin_action: str = "",
    ) -> AgentStepResult:
        run_id = run.id
        node_id = str(node["id"])
        phase = str(node.get("phase") or "")
        state = WorkflowNodeState(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            status=RUNNING,
            iteration=iteration,
            max_iterations=max(1, int(node.get("max_iterations") or 1)),
        )
        db.add(state)
        # The models intentionally use explicit IDs instead of an ORM
        # relationship. Persist the parent first so PostgreSQL never receives
        # AgentStepExecution before its WorkflowNodeState foreign key exists.
        db.flush()
        context_policy = ContextPolicy.model_validate(node.get("context_policy") or {})
        context = self.context_builder.build(db, run=run, node_id=node_id, policy=context_policy)
        prompt = self._prompt_version(db, node=node, workflow_version=workflow_version)
        step = AgentStepExecution(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            workflow_node_state_id=state.id,
            prompt_version_id=prompt.id,
            node_id=node_id,
            phase=phase,
            iteration=iteration,
            attempt=attempt,
            status="running",
            input_hash=context.input_hash,
            input_manifest_json=self._context_manifest(context),
            output_manifest_json={},
            output_refs_json=[],
        )
        db.add(step)
        context_build = ContextBuild(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_execution_id=step.id,
                node_id=node_id,
                policy_version=context.policy_version,
                input_budget_tokens=context.input_budget_tokens,
                estimated_input_tokens=context.estimated_input_tokens,
                selected_tokens=context.estimated_input_tokens,
                discarded_tokens=context.discarded_tokens,
                selected_references_json=[
                    {
                        "kind": reference.kind,
                        "ref_id": reference.ref_id,
                        "label": reference.label,
                        "checksum": reference.checksum,
                        "estimated_tokens": max(1, len(reference.content.encode("utf-8")) // 4),
                        "reason": context.selection_reasons.get(reference.ref_id, "selecionado pela política"),
                    }
                    for reference in context.references
                ],
                discarded_references_json=context.discarded_references,
                selection_reasons_json=context.selection_reasons,
            )
        db.add(context_build)
        emit_event(
            db,
            run.id,
            "agent.sop_started",
            f"{node_id} iniciou a etapa AI-native {phase}.",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            payload={"iteration": iteration, "attempt": attempt, "input_hash": context.input_hash, "prompt": f"{prompt.code}@{prompt.version}"},
        )
        db.flush()
        resolved_plugin_action = plugin_action or f"{'observe' if observation_only else 'execute'}:{attempt}"
        plugin_prompt = self.plugins.prompt_for_node(
            db,
            run=run,
            node=node,
            iteration=iteration,
            action=resolved_plugin_action,
        )
        system_prompt = self._system_prompt(prompt, node, observation_only)
        if plugin_prompt:
            system_prompt = f"{system_prompt}\n\n{plugin_prompt}"
        previous = None
        retry_classification = "initial"
        if attempt > 1:
            previous = (
                db.query(AgentStepExecution)
                .filter_by(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    node_id=node_id,
                    iteration=iteration,
                    status="failed",
                )
                .order_by(AgentStepExecution.attempt.desc())
                .first()
            )
            if previous and previous.error:
                retry_classification = classify_retry(previous.error)
                system_prompt += (
                    "\n\nRetry correction: the previous response failed validation. "
                    f"Correct this error and return a fresh, complete JSON object: {previous.error[:1200]}"
                )
        user_prompt = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, default=str)
        if retry_classification == "schema_repair" and previous and previous.model_call_id:
            previous_call = db.get(ModelCall, previous.model_call_id)
            previous_raw = str(((previous_call.response_json if previous_call else {}) or {}).get("raw") or "")
            if previous_raw:
                system_prompt = (
                    "Repair one previously generated JSON response. Do not add facts, artifacts, files or citations that "
                    "were absent from the previous response. Return only a complete object matching the supplied schema."
                )
                user_prompt = json.dumps(
                    {"validation_error": previous.error[:2000], "previous_response": previous_raw[:160000]},
                    ensure_ascii=False,
                )
        try:
            model_role = self._model_role_for_attempt(node, attempt, retry_classification)
            max_output_tokens = int(
                node.get("observation_max_output_tokens" if observation_only else "max_output_tokens")
                or node.get("max_output_tokens")
                or 0
            )
            model_result = self.gateway.call(
                db=db,
                tenant_id=run.tenant_id,
                run_id=run.id,
                agent_name=node_id,
                model_role=model_role,
                max_output_tokens=max_output_tokens or None,
                cache_scope="global_static" if attempt == 1 else "none",
                routing_policy_version=workflow_version,
                workflow_node_state_id=state.id,
                prompt_version_id=prompt.id,
                input_hash=context.input_hash,
                context_refs=[reference.ref_id for reference in context.references],
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_schema=self._response_schema_for_node(node, observation_only=observation_only),
                invocation_scope=AIInvocationScope(
                    scope_type="factory_run",
                    scope_id=run.id,
                    correlation_id=run.id,
                    policy_version=workflow_version,
                    invocation_id=stable_hash(
                        {"tenant_id": run.tenant_id, "run_id": run.id, "node_id": node_id, "iteration": iteration, "observation_only": observation_only}
                    ),
                    routing_reason=(
                        "retry_escalation"
                        if attempt > 1 and model_role != str(node.get("model_role") or "default")
                        else "protected_quality_role"
                        if model_role in {"reasoning", "code"}
                        else "fast_low_risk_role"
                    ),
                    retry_classification=retry_classification,
                    attempt_number=attempt,
                    envelope=CostEnvelope(
                        soft_budget_usd=round(float(run.ai_budget_usd or get_settings().model_run_budget_usd) * 0.8, 4),
                        hard_budget_usd=float(run.ai_budget_usd or get_settings().model_run_budget_usd),
                        reserved_budget_usd=float(node.get("reserved_budget_usd") or 0.0),
                    ),
                    metadata={"node_id": node_id, "phase": phase, "iteration": iteration, "observation_only": observation_only},
                ),
            )
            model_call_id = str(model_result["id"])
            step.model_call_id = model_call_id
            context_build.ai_invocation_id = str(model_result.get("invocation_id") or "") or None
            db.flush()
            parsed = (model_result.get("content") or {}).get("parsed")
            if not isinstance(parsed, dict):
                raise AINativeExecutionError(f"{node_id} returned a non-object response")
            result_contract = (
                RiskArtifactStepResult
                if observation_only and node_id == "QA Engineer"
                else result_contract_for_node(
                    node_id,
                    workspace_author=bool(node.get("workspace_ownership")),
                )
            )
            allowed_fields = set(result_contract.model_fields)
            irrelevant = {key: value for key, value in parsed.items() if key not in allowed_fields}
            if any(value not in (None, "", [], {}) for value in irrelevant.values()):
                raise AINativeExecutionError(
                    f"{node_id} returned non-empty fields outside its role contract: {sorted(irrelevant)}"
                )
            role_result = result_contract.model_validate({key: value for key, value in parsed.items() if key in allowed_fields})
            result = AgentStepResult.model_validate(role_result.model_dump(mode="json"))
            if result.confidence < 0.65 and model_role == "fast":
                raise AINativeExecutionError(
                    f"{node_id} confidence {result.confidence:.2f} is below the 0.65 escalation threshold"
                )
            if observation_only and result.file_operations:
                raise AINativeExecutionError(f"{node_id} observation attempts cannot mutate files")
            self._validate_result(db, run=run, node=node, result=result, context=context)
            cited = set(result.citations)
            cited_refs = [reference for reference in context.references if reference.ref_id in cited]
            context_build.cited_references_json = [reference.ref_id for reference in cited_refs]
            context_build.cited_tokens = sum(max(1, len(reference.content.encode("utf-8")) // 4) for reference in cited_refs)
            output_refs = self._apply_result(db, run=run, node=node, result=result, step=step, model_call_id=model_call_id)
            self.plugins.finish_cavekit_stages(
                db,
                run=run,
                node=node,
                iteration=iteration,
                action=resolved_plugin_action,
                status="completed",
                stages=[
                    stage
                    for stage in CavekitPolicy.stages_for_action(node, resolved_plugin_action)
                    if stage != "backprop"
                ],
                evidence={
                    "evidence_type": "validated_agent_step",
                    "step_execution_id": step.id,
                    "model_call_id": model_call_id,
                    "output_hash": result.output_hash(),
                    "output_refs": output_refs,
                    "decision": result.decision,
                },
            )
        except Exception as exc:
            if not db.is_active:
                db.rollback()
                raise
            failed_model_call_id = str(getattr(exc, "call_id", "") or "")
            if failed_model_call_id:
                step.model_call_id = failed_model_call_id
            step.status = "failed"
            step.error = str(exc)[:8000]
            step.finished_at = utcnow()
            state.status = FAILED
            state.summary = str(exc)[:8000]
            state.finished_at = utcnow()
            self.plugins.finish_cavekit_stages(
                db,
                run=run,
                node=node,
                iteration=iteration,
                action=resolved_plugin_action,
                status="failed",
                evidence={
                    "evidence_type": "agent_step_failure",
                    "step_execution_id": step.id,
                    "model_call_id": str(step.model_call_id or failed_model_call_id),
                    "error_class": type(exc).__name__,
                },
                error=str(exc),
            )
            db.add(
                LearningSignal(
                    id=str(uuid.uuid4()),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    signal_type="agent.step_failed",
                    source_type="agent_step_execution",
                    source_id=step.id,
                    agent_name=node_id,
                    prompt_version_id=step.prompt_version_id,
                    model_call_id=step.model_call_id,
                    value=-1.0,
                    evidence_json={
                        "iteration": iteration,
                        "attempt": attempt,
                        "error_class": type(exc).__name__,
                        "schema_or_runtime_failure": True,
                        "hallucination_check_failed": "referenced context that was not supplied" in str(exc),
                    },
                    eligible_for_global=False,
                )
            )
            emit_event(
                db,
                run_id,
                "agent.sop_failed",
                f"{node_id} falhou: {str(exc)[:1000]}",
                node_id=node_id,
                phase=phase,
                agent_name=node_id,
                status=FAILED,
                payload={
                    "iteration": iteration,
                    "attempt": attempt,
                    "step_execution_id": step.id,
                    "model_call_id": failed_model_call_id,
                },
            )
            db.commit()
            raise
        step.status = "completed" if result.status == "success" else result.status
        step.decision = result.decision
        step.output_hash = result.output_hash()
        step.output_manifest_json = result.model_dump(mode="json")
        step.output_refs_json = output_refs
        step.finished_at = utcnow()
        state.status = SUCCESS if result.status == "success" else result.status
        state.summary = result.summary
        state.payload_json = {
            "decision": result.decision,
            "confidence": result.confidence,
            "input_hash": context.input_hash,
            "output_hash": step.output_hash,
            "model_call_id": model_call_id,
            "step_execution_id": step.id,
            "output_refs": output_refs,
        }
        state.finished_at = utcnow()
        model_call = db.get(ModelCall, model_call_id)
        if model_call:
            model_call.output_refs_json = output_refs
        db.add(
            LearningSignal(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                signal_type="agent.step_completed",
                source_type="agent_step_execution",
                source_id=step.id,
                agent_name=node_id,
                prompt_version_id=step.prompt_version_id,
                model_call_id=model_call_id,
                value=max(-1.0, min(1.0, (result.confidence - 0.5) * 2.0)),
                evidence_json={
                    "iteration": iteration,
                    "attempt": attempt,
                    "decision": result.decision,
                    "confidence": result.confidence,
                    "prompt_tokens": model_call.prompt_tokens if model_call else 0,
                    "completion_tokens": model_call.completion_tokens if model_call else 0,
                    "cost_usd": model_call.estimated_cost_usd if model_call else 0.0,
                    "latency_seconds": model_call.duration_seconds if model_call else 0.0,
                },
                eligible_for_global=False,
            )
        )
        emit_event(
            db,
            run.id,
            "agent.sop_completed",
            f"{node_id}: {result.summary}",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            status=state.status,
            model_call_id=model_call_id,
            payload={
                "decision": result.decision,
                "confidence": result.confidence,
                "input_hash": context.input_hash,
                "output_hash": step.output_hash,
                "step_execution_id": step.id,
                "output_refs": output_refs,
            },
        )
        db.commit()
        return result

    def _validate_result(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        result: AgentStepResult,
        context: ContextBundle,
    ) -> None:
        node_id = str(node["id"])
        allowed_decisions = set(node.get("allowed_decisions") or [])
        if allowed_decisions and result.decision not in allowed_decisions:
            raise AINativeExecutionError(
                f"{node_id} decision {result.decision!r} is not allowed; expected one of {sorted(allowed_decisions)}"
            )
        reference_ids = {reference.ref_id for reference in context.references}
        invalid_citations = set(result.citations) - reference_ids
        invalid_sources = {
            source
            for artifact in result.artifacts
            for source in artifact.source_refs
            if source not in reference_ids
        }
        if invalid_citations or invalid_sources:
            raise AINativeExecutionError(
                f"{node_id} referenced context that was not supplied: {sorted(invalid_citations | invalid_sources)}"
            )
        paths = [operation.path for operation in result.file_operations]
        if len(paths) != len(set(paths)):
            raise AINativeExecutionError(f"{node_id} returned duplicate file operations")
        workflow_version = str((run.context_manifest_json or {}).get("workflow_version") or "")
        if workflow_version == "2.14.0":
            for path in paths:
                validate_workspace_path_ownership(node_id, path)
        root = run_workspace(run.id, run.tenant_id)
        if node_id == "Engineer":
            prior_generated_files = (
                db.query(FileChange)
                .filter_by(tenant_id=run.tenant_id, run_id=run.id)
                .filter(FileChange.file_path.like("generated_app/%"))
                .count()
            )
            if prior_generated_files == 0:
                if len(paths) > 32:
                    raise AINativeExecutionError("Engineer initial output must contain at most 32 file operations")
                total_file_chars = sum(len(operation.content or operation.patch) for operation in result.file_operations)
                if total_file_chars > 90_000:
                    raise AINativeExecutionError(
                        f"Engineer initial output exceeds the 90000-character source budget: {total_file_chars}"
                    )
                required_paths = {
                    "generated_app/backend/app/main.py",
                    "generated_app/frontend/package.json",
                    "generated_app/frontend/app/page.tsx",
                    "generated_app/README.md",
                }
                missing = required_paths - set(paths)
                has_backend_test = any(path.startswith("generated_app/backend/tests/") for path in paths)
                backend_test_missing = workflow_version != "2.14.0" and not has_backend_test
                if missing or backend_test_missing:
                    detail = sorted(missing | ({"generated_app/backend/tests/<test>.py"} if backend_test_missing else set()))
                    raise AINativeExecutionError(f"Engineer initial full-stack output is incomplete: {detail}")
        for operation in result.file_operations:
            path = safe_join(root, operation.path)
            exists = path.exists()
            if operation.operation == "create" and exists:
                raise AINativeExecutionError(f"create cannot overwrite existing file {operation.path}")
            if operation.operation in {"update", "patch"} and not exists:
                raise AINativeExecutionError(f"{operation.operation} requires existing file {operation.path}")
            if operation.operation in {"update", "patch"}:
                if not operation.base_sha256:
                    raise AINativeExecutionError(f"{operation.operation} requires base_sha256 for {operation.path}")
                actual_hash = hashlib.sha256(path.read_text().encode()).hexdigest()
                if operation.base_sha256 != actual_hash:
                    raise AINativeExecutionError(f"stale file update rejected for {operation.path}")
            if operation.operation == "patch":
                apply_unified_patch(path.read_text(), operation.patch)

    def _apply_result(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        node: dict[str, Any],
        result: AgentStepResult,
        step: AgentStepExecution,
        model_call_id: str,
    ) -> list[str]:
        node_id = str(node["id"])
        outputs: list[str] = []
        allowed_tools = set(node.get("allowed_tools") or [])
        if result.file_operations and "write_workspace" not in allowed_tools:
            raise AINativeExecutionError(f"{node_id} is not allowed to mutate the workspace")
        expected = set(node.get("outputs") or [])
        produced = {artifact.name for artifact in result.artifacts}
        if expected and not expected.intersection(produced) and node_id not in {"QA Engineer", "Quality Governor"}:
            raise AINativeExecutionError(f"{node_id} did not produce any declared artifact: {sorted(expected)}")
        for artifact_output in result.artifacts:
            artifact = self._persist_artifact(db, run, node_id, artifact_output, step.id, model_call_id)
            outputs.append(artifact.name)
        if node_id == "Code Reviewer" and node.get("ponytail_enabled"):
            audit = self._persist_ponytail_audit(
                db,
                run=run,
                step=step,
                model_call_id=model_call_id,
                findings=result.minimality_findings,
                citations=result.citations,
            )
            outputs.append(audit.name)
        for operation in result.file_operations:
            change = self._persist_file(db, run, node_id, operation, step.id, model_call_id)
            outputs.append(change.file_path)
        if node_id == "Engineer" and node.get("ponytail_enabled"):
            debt = self._persist_ponytail_debt(db, run=run, step=step, model_call_id=model_call_id)
            outputs.append(debt.name)
        for requirement_output in result.requirements:
            requirement = (
                db.query(Requirement)
                .filter_by(tenant_id=run.tenant_id, run_id=run.id, requirement_id=requirement_output.requirement_id)
                .first()
            )
            if not requirement:
                requirement = Requirement(
                    id=str(uuid.uuid4()),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    requirement_id=requirement_output.requirement_id,
                    title=requirement_output.title,
                    description=requirement_output.description,
                    priority=requirement_output.priority,
                    source=f"model_call:{model_call_id}",
                    status="pending",
                )
                db.add(requirement)
            else:
                requirement.title = requirement_output.title
                requirement.description = requirement_output.description
                requirement.priority = requirement_output.priority
            outputs.append(requirement_output.requirement_id)
            for index, criterion in enumerate(requirement_output.acceptance_criteria, start=1):
                criterion_id = f"{requirement_output.requirement_id}-AC-{index:02d}"
                existing = (
                    db.query(AcceptanceCriterion)
                    .filter_by(tenant_id=run.tenant_id, run_id=run.id, criterion_id=criterion_id)
                    .first()
                )
                if not existing:
                    db.add(
                        AcceptanceCriterion(
                            id=str(uuid.uuid4()),
                            tenant_id=run.tenant_id,
                            run_id=run.id,
                            criterion_id=criterion_id,
                            requirement_id=requirement_output.requirement_id,
                            title=criterion[:500],
                            gherkin=criterion,
                            priority=requirement_output.priority,
                            status="pending",
                        )
                    )
        return outputs

    def _persist_ponytail_audit(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        step: AgentStepExecution,
        model_call_id: str,
        findings: list[Any],
        citations: list[str],
    ) -> Artifact:
        existing = (
            db.query(Artifact)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id="Code Reviewer",
                name="PONYTAIL_AUDIT.md",
                step_execution_id=step.id,
            )
            .first()
        )
        if existing:
            return existing
        lines = [
            "# PONYTAIL_AUDIT.md",
            "",
            "Auditoria de minimalidade baseada no diff real. Segurança, correção e acessibilidade são avaliadas separadamente.",
            "",
        ]
        if findings:
            lines.extend(["| Tag | Local | Finding | Substituição | Linhas estimadas |", "|---|---|---|---|---:|"])
            for finding in findings:
                location = f"`{finding.path}:{finding.line}`" if finding.line else f"`{finding.path}`"
                finding_text = finding.finding.replace("|", "\\|")
                replacement = finding.replacement.replace("|", "\\|")
                lines.append(
                    f"| {finding.tag} | {location} | {finding_text} | {replacement} | {finding.estimated_lines_removed} |"
                )
            lines.extend(
                [
                    "",
                    f"Potencial estimado pelo reviewer: {sum(item.estimated_lines_removed for item in findings)} linhas. Não é economia realizada.",
                ]
            )
        else:
            lines.append("Lean already. Ship.")
        artifact = self._persist_artifact(
            db,
            run,
            "Code Reviewer",
            ArtifactOutput(
                name="PONYTAIL_AUDIT.md",
                content="\n".join(lines),
                audience="internal",
                evidence_classification="estimated" if findings else "real",
                source_refs=list(dict.fromkeys([*citations, model_call_id, step.id])),
            ),
            step.id,
            model_call_id,
        )
        self.plugins.record_result(
            db,
            run=run,
            plugin_name="ponytail",
            command="audit",
            node_id="Code Reviewer",
            iteration=step.iteration,
            status="completed",
            output={
                "artifact_id": artifact.id,
                "finding_count": len(findings),
                "estimated_lines_removed": sum(item.estimated_lines_removed for item in findings),
            },
        )
        return artifact

    def _persist_ponytail_debt(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        step: AgentStepExecution,
        model_call_id: str,
    ) -> Artifact:
        existing = (
            db.query(Artifact)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id="Engineer",
                name="PONYTAIL_DEBT.md",
                step_execution_id=step.id,
            )
            .first()
        )
        if existing:
            return existing
        changes = (
            db.query(FileChange)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id)
            .filter(FileChange.file_path.like("generated_app/%"))
            .order_by(FileChange.created_at.asc())
            .all()
        )
        latest_by_path = {change.file_path: change.after_content for change in changes}
        items = PonytailPolicy.scan_debt(latest_by_path.items())
        content = PonytailPolicy.debt_markdown(items)
        artifact = Artifact(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Engineer",
            artifact_type="markdown",
            name="PONYTAIL_DEBT.md",
            path="docs/PONYTAIL_DEBT.md",
            content=content,
            audience="internal",
            evidence_classification="calculated",
            source_refs_json=[change.id for change in changes],
            model_call_id=model_call_id or None,
            step_execution_id=step.id,
            metadata_json={
                "generated_by": "ponytail-debt",
                "provenance": "deterministic_scan",
                "marker_count": len(items),
                "markers_without_trigger": sum(not item.has_trigger for item in items),
            },
        )
        db.add(artifact)
        storage_key = object_storage.put_text(
            run.tenant_id,
            run.id,
            "artifacts",
            artifact.name,
            content,
            content_type="text/markdown; charset=utf-8",
        )
        artifact.metadata_json = {**artifact.metadata_json, "storage_key": storage_key or ""}
        emit_event(
            db,
            run.id,
            "artifact.created",
            "Ponytail gerou o ledger determinístico de simplificações.",
            node_id="Engineer",
            phase=step.phase,
            agent_name="Engineer",
            model_call_id=model_call_id,
            payload={"artifact_id": artifact.id, "name": artifact.name, "step_execution_id": step.id},
        )
        self.plugins.record_result(
            db,
            run=run,
            plugin_name="ponytail",
            command="debt",
            node_id="Engineer",
            iteration=step.iteration,
            status="completed",
            output={
                "artifact_id": artifact.id,
                "marker_count": len(items),
                "markers_without_trigger": sum(not item.has_trigger for item in items),
            },
        )
        return artifact

    def _persist_artifact(
        self,
        db: Session,
        run: WorkflowRun,
        node_id: str,
        output: ArtifactOutput,
        step_execution_id: str,
        model_call_id: str,
    ) -> Artifact:
        artifact = Artifact(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id=node_id,
            artifact_type=output.artifact_type,
            name=output.name,
            path=f"docs/{output.name}",
            content=output.content,
            audience=output.audience,
            evidence_classification=output.evidence_classification,
            source_refs_json=list(dict.fromkeys([*output.source_refs, model_call_id, step_execution_id])),
            model_call_id=model_call_id,
            step_execution_id=step_execution_id,
            metadata_json={"generated_by": node_id, "provenance": "model_output", "model_call_id": model_call_id},
        )
        db.add(artifact)
        storage_key = object_storage.put_text(
            run.tenant_id,
            run.id,
            "artifacts",
            output.name,
            output.content,
            content_type="text/markdown; charset=utf-8" if output.artifact_type == "markdown" else "text/plain; charset=utf-8",
        )
        artifact.metadata_json = {**artifact.metadata_json, "storage_key": storage_key or ""}
        emit_event(
            db,
            run.id,
            "artifact.created",
            f"{node_id} criou {output.name} a partir de uma saída validada do modelo.",
            node_id=node_id,
            agent_name=node_id,
            model_call_id=model_call_id,
            payload={"artifact_id": artifact.id, "name": output.name, "step_execution_id": step_execution_id, "storage_key": storage_key or ""},
        )
        return artifact

    def _persist_file(
        self,
        db: Session,
        run: WorkflowRun,
        node_id: str,
        operation: FileOperation,
        step_execution_id: str,
        model_call_id: str,
    ) -> FileChange:
        if str((run.context_manifest_json or {}).get("workflow_version") or "") == "2.14.0":
            validate_workspace_path_ownership(node_id, operation.path)
        root = run_workspace(run.id, run.tenant_id)
        path = safe_join(root, operation.path)
        exists = path.exists()
        before = path.read_text() if exists else ""
        if operation.operation == "create" and exists:
            raise AINativeExecutionError(f"create cannot overwrite existing file {operation.path}")
        if operation.operation in {"update", "patch"} and not exists:
            raise AINativeExecutionError(f"{operation.operation} requires existing file {operation.path}")
        if operation.operation in {"update", "patch"}:
            if not operation.base_sha256:
                raise AINativeExecutionError(f"{operation.operation} requires base_sha256 for {operation.path}")
            actual_hash = hashlib.sha256(before.encode()).hexdigest()
            if operation.base_sha256 != actual_hash:
                raise AINativeExecutionError(f"stale file update rejected for {operation.path}")
        after = apply_unified_patch(before, operation.patch) if operation.operation == "patch" else operation.content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after)
        change_type = "updated" if exists else "created"
        change = FileChange(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id=node_id,
            file_path=operation.path,
            change_type=change_type,
            before_content=before,
            after_content=after,
            diff=unified_diff(operation.path, before, after),
            model_call_id=model_call_id,
            step_execution_id=step_execution_id,
        )
        db.add(change)
        storage_key = object_storage.put_text(run.tenant_id, run.id, "workspace", operation.path, after)
        emit_event(
            db,
            run.id,
            f"file.{change_type}",
            f"Arquivo {operation.path} {change_type} por saída validada do modelo.",
            node_id=node_id,
            agent_name=node_id,
            model_call_id=model_call_id,
            payload={"file_path": operation.path, "step_execution_id": step_execution_id, "storage_key": storage_key or ""},
        )
        emit_event(
            db,
            run.id,
            "file.diff",
            f"Diff auditável criado para {operation.path}.",
            node_id=node_id,
            agent_name=node_id,
            model_call_id=model_call_id,
            payload={"file_change_id": change.id, "file_path": operation.path},
        )
        return change

    def _build_traceability(self, db: Session, run: WorkflowRun) -> None:
        requirements = db.query(Requirement).filter_by(tenant_id=run.tenant_id, run_id=run.id, priority="P0").all()
        workflow_version = str((run.context_manifest_json or {}).get("workflow_version") or "")
        if workflow_version in {"2.13.2", "2.14.0"}:
            self._build_verified_contract_traceability(db, run=run, requirements=requirements)
            return
        files = (
            db.query(FileChange)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id)
            .filter(FileChange.file_path.like("generated_app/%"))
            .order_by(FileChange.created_at.asc())
            .all()
        )
        passing = (
            db.query(TestReport)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, status="passed")
            .order_by(TestReport.created_at.desc())
            .first()
        )
        if not passing or not files:
            return
        distinct_paths = list(dict.fromkeys(change.file_path for change in files))
        for index, requirement in enumerate(requirements):
            existing = (
                db.query(RequirementTrace)
                .filter_by(tenant_id=run.tenant_id, run_id=run.id, requirement_id=requirement.requirement_id)
                .first()
            )
            if existing:
                continue
            db.add(
                RequirementTrace(
                    id=str(uuid.uuid4()),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    requirement_id=requirement.requirement_id,
                    file_path=distinct_paths[index % len(distinct_paths)],
                    test_name=passing.command,
                    evidence=f"test_report:{passing.id}",
                    status="pass",
                )
            )
            requirement.status = "pass"
        emit_event(
            db,
            run.id,
            "traceability.updated",
            "Rastreabilidade calculada a partir de requirements, arquivos e testes persistidos.",
            node_id="QA Engineer",
            phase="testing",
            payload={"requirements": len(requirements), "test_report_id": passing.id},
        )

    def _build_verified_contract_traceability(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        requirements: list[Requirement],
    ) -> None:
        """Persist only model-declared spec links confirmed by a passing allowlisted suite."""

        passing_reports = (
            db.query(TestReport)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, status="passed")
            .order_by(TestReport.created_at.desc())
            .all()
        )
        if not passing_reports:
            return
        units = (
            db.query(ExecutionUnit)
            .filter_by(
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id="Engineer",
                unit_type="file_batch",
                status="completed",
            )
            .order_by(ExecutionUnit.iteration.desc(), ExecutionUnit.order_index.asc())
            .all()
        )
        files_by_path = {
            change.file_path: change
            for change in db.query(FileChange)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id)
            .filter(FileChange.file_path.like("generated_app/%"))
            .order_by(FileChange.created_at.asc())
            .all()
        }
        criteria_by_requirement: dict[str, list[str]] = {}
        for criterion in db.query(AcceptanceCriterion).filter_by(tenant_id=run.tenant_id, run_id=run.id).all():
            criteria_by_requirement.setdefault(criterion.requirement_id, []).append(criterion.criterion_id)

        created = 0
        verified_requirements: set[str] = set()
        report_refs: dict[str, list[str]] = {}
        for requirement in requirements:
            requirement_units = [
                unit
                for unit in units
                if requirement.requirement_id in set((unit.context_manifest_json or {}).get("requirement_refs") or [])
            ]
            for unit in requirement_units:
                manifest = unit.context_manifest_json or {}
                invariant_refs = list(dict.fromkeys(manifest.get("invariant_refs") or []))
                verification_tests = list(dict.fromkeys(manifest.get("verification_tests") or []))
                if not invariant_refs or not verification_tests:
                    continue
                for path in unit.targets_json or []:
                    change = files_by_path.get(path)
                    if not change:
                        continue
                    report = self._passing_report_for_path(passing_reports, path)
                    if not report:
                        continue
                    change.spec_refs_json = list(
                        dict.fromkeys(
                            [
                                *(change.spec_refs_json or []),
                                requirement.requirement_id,
                                *criteria_by_requirement.get(requirement.requirement_id, []),
                                *invariant_refs,
                                *verification_tests,
                            ]
                        )
                    )
                    for test_name in verification_tests:
                        existing = (
                            db.query(RequirementTrace)
                            .filter_by(
                                tenant_id=run.tenant_id,
                                run_id=run.id,
                                requirement_id=requirement.requirement_id,
                                file_path=path,
                                test_name=test_name,
                            )
                            .first()
                        )
                        if existing:
                            verified_requirements.add(requirement.requirement_id)
                            continue
                        db.add(
                            RequirementTrace(
                                id=str(uuid.uuid4()),
                                tenant_id=run.tenant_id,
                                run_id=run.id,
                                requirement_id=requirement.requirement_id,
                                file_path=path,
                                test_name=test_name,
                                evidence=f"execution_unit:{unit.id};test_report:{report.id}",
                                criterion_ids_json=criteria_by_requirement.get(requirement.requirement_id, []),
                                invariant_ids_json=invariant_refs,
                                test_report_id=report.id,
                                provenance="verified_contract",
                                status="pass",
                            )
                        )
                        created += 1
                        verified_requirements.add(requirement.requirement_id)
                        report_refs.setdefault(report.id, []).extend(
                            [requirement.requirement_id, test_name, *invariant_refs]
                        )
            if requirement.requirement_id in verified_requirements:
                requirement.status = "pass"

        for report in passing_reports:
            if report.id in report_refs:
                report.spec_refs_json = list(dict.fromkeys([*(report.spec_refs_json or []), *report_refs[report.id]]))
        emit_event(
            db,
            run.id,
            "traceability.updated",
            "Rastreabilidade contratual verificada a partir do manifesto, arquivos e suites allowlisted.",
            node_id="QA Engineer",
            phase="testing",
            payload={
                "requirements_total": len(requirements),
                "requirements_verified": len(verified_requirements),
                "traces_created": created,
                "provenance": "verified_contract",
            },
        )

    @staticmethod
    def _passing_report_for_path(reports: list[TestReport], path: str) -> Optional[TestReport]:
        if "/backend/" in path:
            marker = "generated_app/backend/tests"
        elif "/frontend/" in path:
            marker = "generated_app/frontend run test"
        else:
            marker = ""
        exact_tests = [
            report
            for report in reports
            if "generated_app/backend/tests" in report.command
            or report.command.strip() == "npm --prefix generated_app/frontend run test"
        ]
        return next(
            (report for report in exact_tests if marker and marker in report.command),
            exact_tests[0] if exact_tests else None,
        )

    def _prompt_version(self, db: Session, *, node: dict[str, Any], workflow_version: str) -> PromptVersion:
        skill_id = str(node.get("skill") or "")
        code = f"workflow.{skill_id or str(node['id']).lower().replace(' ', '_')}"
        version = workflow_version or "2.0.0"
        existing = db.query(PromptVersion).filter_by(tenant_id="global", code=code, version=version, status="active").first()
        if existing:
            return existing
        prompt_path = Path("prompts/agents") / f"{skill_id}.md"
        skill_path = Path("skills") / f"{skill_id}.skill.yaml"
        common_path = Path("prompts/agents/common_system_prompt.md")
        content = "\n\n".join(
            value
            for value in [
                common_path.read_text() if common_path.exists() else "",
                prompt_path.read_text() if prompt_path.exists() else "",
                skill_path.read_text() if skill_path.exists() else "",
            ]
            if value
        )
        prompt = PromptVersion(
            id=str(uuid.uuid4()),
            tenant_id="global",
            code=code,
            version=version,
            name=f"{node['id']} AI-native workflow prompt",
            system_prompt=content,
            output_schema_json=self._response_schema_for_node(node, observation_only=False),
            examples_json=[],
            status="active",
        )
        db.add(prompt)
        db.flush()
        return prompt

    @staticmethod
    def _response_schema_for_node(node: dict[str, Any], *, observation_only: bool) -> dict[str, Any]:
        node_id = str(node.get("id") or "")
        contract = (
            RiskArtifactStepResult
            if observation_only and node_id == "QA Engineer"
            else result_contract_for_node(
                node_id,
                workspace_author=bool(node.get("workspace_ownership")),
            )
        )
        schema = contract.model_json_schema()
        allowed_decisions = list(node.get("allowed_decisions") or [])
        if allowed_decisions and "decision" in (schema.get("properties") or {}):
            schema["properties"]["decision"]["enum"] = allowed_decisions
        return schema

    @staticmethod
    def _system_prompt(prompt: PromptVersion, node: dict[str, Any], observation_only: bool) -> str:
        expected = ", ".join(node.get("outputs") or []) or "validated structured output"
        decisions = ", ".join(node.get("allowed_decisions") or []) or "success"
        mode = (
            "This is an observation pass. Read the persisted tool evidence, produce the final report and decision, and do not mutate files."
            if observation_only
            else "Produce the deliverables directly; they will be validated and applied by the factory."
        )
        engineering_contract = ""
        if str(node.get("id")) == "Engineer":
            test_requirement = (
                "QA Engineer owns and writes the test files after implementation; do not author test paths. "
                if node.get("qa_owns_tests")
                else "Include at least one generated_app/backend/tests/test_*.py. "
            )
            engineering_contract = (
                " Generate a runnable, domain-specific full-stack application, not a generic placeholder. "
                "File operations must include a FastAPI backend and a Next.js frontend with package "
                "scripts named test, build, test:visual and test:a11y. Required paths include "
                "generated_app/backend/app/main.py, "
                "generated_app/frontend/package.json, generated_app/frontend/app/page.tsx and generated_app/README.md. "
                f"{test_requirement}"
                "Use only dependencies already available in the sandbox and never include installation commands."
            )
        ownership_contract = ""
        if node.get("workspace_ownership"):
            ownership_contract = (
                " You may author only these path patterns: "
                + ", ".join(str(pattern) for pattern in node["workspace_ownership"])
                + ". Every update or patch requires the current base_sha256."
            )
            if str(node.get("id")) == "QA Engineer":
                ownership_contract += (
                    " Write the backend, frontend and E2E tests before requesting the allowlisted test profiles."
                )
        mutation_contract = (
            " File operations are forbidden for this role; return artifacts and other declared outputs only."
            if observation_only or "write_workspace" not in set(node.get("allowed_tools") or [])
            else ""
        )
        minimal_solution_contract = (
            "" if node.get("ponytail_enabled") else AINativeWorkflowExecutor._minimal_solution_guardrail(node)
        )
        return (
            f"{prompt.system_prompt}\n\n"
            "Return JSON only and conform exactly to the supplied AgentStepResult JSON schema. "
            "Do not reveal hidden chain-of-thought; summary must contain only concise, auditable reasoning. "
            "Never output shell commands, credentials or paths outside generated_app/. "
            "Use only supplied ContextReference ref_id values in citations and artifact source_refs. "
            f"Required artifact names for this role: {expected}. Allowed decision values: {decisions}. {mode}"
            f"{engineering_contract}{ownership_contract}{mutation_contract}{minimal_solution_contract}"
        )

    @staticmethod
    def _context_manifest(context: ContextBundle) -> dict[str, Any]:
        return {
            "tenant_id": context.tenant_id,
            "run_id": context.run_id,
            "node_id": context.node_id,
            "input_hash": context.input_hash,
            "references": [
                {"kind": reference.kind, "ref_id": reference.ref_id, "label": reference.label, "checksum": reference.checksum}
                for reference in context.references
            ],
            "constraints": context.constraints,
            "policy_version": context.policy_version,
            "input_budget_tokens": context.input_budget_tokens,
            "estimated_input_tokens": context.estimated_input_tokens,
            "discarded_tokens": context.discarded_tokens,
            "discarded_references": context.discarded_references,
            "selection_reasons": context.selection_reasons,
        }

    @staticmethod
    def _model_role_for_attempt(node: dict[str, Any], attempt: int, retry_classification: str = "initial") -> str:
        configured = str(node.get("model_role") or "default")
        if attempt > 1 and configured == "fast" and retry_classification == "semantic_escalation":
            return "reasoning"
        return configured

    @staticmethod
    def _next_edge(edges: list[dict[str, Any]], node_id: str, decision: str) -> Optional[dict[str, Any]]:
        for edge in edges:
            if str(edge.get("from")) == node_id and condition_matches(edge.get("condition"), decision):
                return edge
        return None

    @staticmethod
    def _restored_iterations(db: Session, run: WorkflowRun) -> dict[str, int]:
        rows = db.query(AgentStepExecution).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        iterations: dict[str, int] = {}
        for row in rows:
            iterations[row.node_id] = max(iterations.get(row.node_id, 1), row.iteration)
        return iterations

    @staticmethod
    def _restored_edge_iterations(db: Session, run: WorkflowRun) -> dict[str, int]:
        events = db.query(AgentEvent).filter_by(
            tenant_id=run.tenant_id, run_id=run.id, event_type="agent.handoff"
        ).all()
        counts: dict[str, int] = {}
        for event in events:
            source = str((event.payload_json or {}).get("from_agent") or "")
            target = str((event.payload_json or {}).get("to_agent") or "")
            if source and target:
                key = f"{source}->{target}"
                counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _restored_completed_step_count(db: Session, run: WorkflowRun, current_node: str) -> int:
        rows = db.query(AgentStepExecution).filter_by(
            tenant_id=run.tenant_id, run_id=run.id, status="completed"
        ).all()
        completed = {(row.node_id, row.iteration) for row in rows}
        current_iteration = max((row.iteration for row in rows if row.node_id == current_node), default=0)
        return max(0, len(completed) - (1 if current_iteration else 0))

    @staticmethod
    def _completed_result(db: Session, run: WorkflowRun, node_id: str, iteration: int) -> Optional[AgentStepResult]:
        row = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, iteration=iteration, status="completed")
            .order_by(AgentStepExecution.attempt.desc())
            .first()
        )
        if not row or not row.output_manifest_json:
            return None
        return AgentStepResult.model_validate(row.output_manifest_json)

    @staticmethod
    def _latest_step_attempt(db: Session, run: WorkflowRun, node_id: str, iteration: int) -> int:
        row = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, iteration=iteration, status="completed")
            .order_by(AgentStepExecution.attempt.desc())
            .first()
        )
        return int(row.attempt) if row else 0

    @staticmethod
    def _latest_any_step_attempt(db: Session, run: WorkflowRun, node_id: str, iteration: int) -> int:
        row = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, iteration=iteration)
            .order_by(AgentStepExecution.attempt.desc())
            .first()
        )
        return int(row.attempt) if row else 0

    @staticmethod
    def _override_step_decision(db: Session, run: WorkflowRun, node_id: str, iteration: int, decision: str) -> None:
        row = (
            db.query(AgentStepExecution)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id, node_id=node_id, iteration=iteration)
            .order_by(AgentStepExecution.attempt.desc())
            .first()
        )
        if row:
            row.decision = decision
            row.output_manifest_json = {**(row.output_manifest_json or {}), "decision": decision}

    @staticmethod
    def _fail_run(db: Session, run: WorkflowRun, reason: str) -> WorkflowRun:
        run_id = run.id
        tenant_id = run.tenant_id
        db.rollback()
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first() or run
        run.status = FAILED
        run.current_phase = "blocked"
        run.finished_at = utcnow()
        release_workflow_slot(db, run.id)
        emit_event(
            db,
            run.id,
            "run.failed",
            reason,
            node_id=run.current_node,
            phase=run.current_phase,
            status=FAILED,
            payload={"reason": reason, "generation_mode": run.generation_mode},
        )
        db.commit()
        db.refresh(run)
        return run

    @staticmethod
    def _pause_for_budget(db: Session, run: WorkflowRun, reason: str) -> WorkflowRun:
        run_id = run.id
        tenant_id = run.tenant_id
        db.rollback()
        run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first() or run
        run.status = PENDING
        run.current_phase = "budget_paused"
        run.finished_at = None
        release_workflow_slot(db, run.id)
        emit_event(
            db,
            run.id,
            "run.budget_paused",
            reason,
            node_id=run.current_node,
            phase=run.current_phase,
            status=PENDING,
            payload={"reason": reason, "generation_mode": run.generation_mode, "retry_allowed": False},
        )
        db.commit()
        db.refresh(run)
        return run
