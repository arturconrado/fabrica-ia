import io
import hashlib
import json
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, require_roles
from app.core.config import get_settings
from app.core.status import APPROVED_FOR_HOMOLOGATION, CANCELLED, FAILED, REJECTED
from app.db.session import SessionLocal, get_db
from app.events.sse import event_stream
from app.models import (
    AIInvocation,
    AcceptanceCriterion,
    AgentMessage,
    AgentRunState,
    AgentEvent,
    AgentStepExecution,
    AgentWorkItem,
    ApprovalRequest,
    Artifact,
    ContextBuild,
    ExecutionUnit,
    ArtifactFragment,
    FileChange,
    HomologationPackage,
    HomologationReport,
    ModelCall,
    PluginInvocation,
    Project,
    QualityGate,
    QualityScore,
    Requirement,
    RequirementTrace,
    TestReport,
    WorkflowNodeState,
    WorkflowDefinition,
    WorkflowRun,
    utcnow,
)
from app.schemas import EnterpriseRunCreate, HumanDecision, RunCreate
from app.schemas.operational import RunPluginAnalysisResponse, RunWorkspaceResponse, TokenAnalysisResponse
from app.providers.object_storage import object_storage
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict
from app.service_delivery.capacity import acquire_workflow_slot, release_workflow_slot
from app.workflow.temporal_outbox import enqueue_cancel, enqueue_signal, enqueue_start
from app.api.routes_workflows import serialize_workflow_topology
from app.plugins import FactoryPluginRuntime
from app.plugins.ponytail import PonytailPolicy

router = APIRouter(prefix="/runs", tags=["runs"])
OPERATIONAL_ROLES = ("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
get_current_principal = require_roles(*OPERATIONAL_ROLES)
AI_NATIVE_REQUIRED_NODES = {
    "Demand Classifier",
    "Acceptance Criteria Architect",
    "Scope Governor",
    "Product Manager",
    "UX UI Designer",
    "Architect",
    "Data Architect",
    "API Contract Engineer",
    "Project Manager",
    "Engineer",
    "Code Reviewer",
    "QA Engineer",
    "Visual QA Agent",
    "Accessibility QA Agent",
    "Security Engineer",
    "DevOps Engineer",
    "Release Manager",
    "Quality Governor",
}


def _enterprise_demand(payload: EnterpriseRunCreate) -> str:
    compliance = ", ".join(payload.compliance) if payload.compliance else "enterprise baseline"
    integrations = ", ".join(payload.integrations) if payload.integrations else "no external integrations"
    return (
        f"{payload.prompt}\n\n"
        "Enterprise operating constraints:\n"
        f"- Template: {payload.template}\n"
        f"- Industry: {payload.industry}\n"
        f"- Quality profile: {payload.quality_profile}\n"
        f"- Compliance targets: {compliance}\n"
        f"- Integrations: {integrations}\n"
        f"- Data sensitivity: {payload.data_sensitivity}\n"
        "- Mandatory output: requirements P0/P1/P2, acceptance criteria, traceability matrix, generated app, "
        "evidence-driven correction when a real check fails, final pytest pass, 17 evidence-classified quality gates, "
        "provisional HRS and an explicit human approval checkpoint before final delivery."
    )


def _get_run_or_404(db: Session, run_id: str, principal: Principal) -> WorkflowRun:
    run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=principal.tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _ensure_controllable(run: WorkflowRun) -> None:
    if run.status in {FAILED, CANCELLED, REJECTED, APPROVED_FOR_HOMOLOGATION, "cancel_requested"}:
        raise HTTPException(status_code=409, detail=f"Run is terminal and cannot be controlled: {run.status}")


def _require_temporal_workflow(run: WorkflowRun) -> None:
    if not run.temporal_workflow_id:
        raise HTTPException(status_code=409, detail="Production-only controls require a Temporal workflow id")


def _uses_temporal() -> bool:
    return get_settings().workflow_backend.lower() == "temporal"


def _create_scheduled_run(
    db: Session,
    *,
    tenant_id: str,
    demand: str,
    project_id: Optional[str] = None,
    project_name: str = "Enterprise Build",
) -> WorkflowRun:
    project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
    if project_id and not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project and not project_name:
        raise HTTPException(status_code=422, detail="project_id or project_name is required")
    if not project:
        project = Project(id=str(uuid.uuid4()), tenant_id=tenant_id, name=project_name, description="Production-only enterprise build.")
        db.add(project)
        db.flush()
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand=demand,
        status="scheduled",
        current_phase="temporal_scheduled",
        current_node="Temporal Worker",
        provider="production-litellm",
    )
    db.add(run)
    db.flush()
    acquire_workflow_slot(db, run.id)
    if _uses_temporal():
        enqueue_start(db, run)
        run.status = "temporal_dispatch_pending"
    return run


@router.post("")
async def post_run(
    payload: RunCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    if not db.query(Project).filter_by(id=payload.project_id, tenant_id=principal.tenant_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if get_settings().runtime_profile.lower() != "test":
        raise HTTPException(
            status_code=409,
            detail="Direct generic runs are test-only; use the contracted MVP flow and a versioned supported blueprint executor",
        )
    if not _uses_temporal():
        run = provider.start_interactive_enterprise_run(
            db,
            demand=payload.demand,
            project_id=payload.project_id,
            tenant_id=principal.tenant_id,
        )
        audit(db, principal, "run.created", "run", run.id, {"workflow_id": run.workflow_id, "backend": "homologation"})
        db.commit()
        return model_to_dict(run)
    run = _create_scheduled_run(db, tenant_id=principal.tenant_id, demand=payload.demand, project_id=payload.project_id)
    audit(db, principal, "run.created", "run", run.id, {"workflow_id": run.workflow_id})
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.post("/enterprise")
async def post_enterprise_run(
    payload: EnterpriseRunCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    if get_settings().runtime_profile.lower() != "test":
        raise HTTPException(
            status_code=409,
            detail="Direct enterprise runs are test-only; use the contracted MVP flow with an approved MvpSpec and entitlement",
        )
    if payload.data_sensitivity.lower() in {"regulated", "restricted", "highly_confidential"}:
        raise HTTPException(status_code=422, detail="Regulated/restricted data is not allowed in the assisted pilot")
    demand = _enterprise_demand(payload)
    if not _uses_temporal():
        run = provider.start_interactive_enterprise_run(
            db,
            demand=demand,
            project_name=payload.project_name,
            tenant_id=principal.tenant_id,
        )
        audit(
            db,
            principal,
            "run.enterprise_created",
            "run",
            run.id,
            {"template": payload.template, "quality_profile": payload.quality_profile, "backend": "homologation"},
        )
        db.commit()
        return model_to_dict(run)
    run = _create_scheduled_run(
        db,
        tenant_id=principal.tenant_id,
        demand=demand,
        project_name=payload.project_name,
    )
    audit(
        db,
        principal,
        "run.enterprise_created",
        "run",
        run.id,
        {
            "template": payload.template,
            "industry": payload.industry,
            "quality_profile": payload.quality_profile,
            "compliance": payload.compliance,
            "temporal_workflow_id": run.temporal_workflow_id,
        },
    )
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.get("")
def get_runs(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    rows = db.query(WorkflowRun).filter_by(tenant_id=principal.tenant_id).order_by(WorkflowRun.created_at.desc()).all()
    data = []
    for run in rows:
        item = model_to_dict(run)
        project = db.get(Project, run.project_id)
        item["project"] = model_to_dict(project) if project else None
        data.append(item)
    return data


@router.get("/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    item = model_to_dict(run)
    project = db.get(Project, run.project_id)
    item["project"] = model_to_dict(project) if project else None
    return item


@router.get("/{run_id}/workspace", response_model=RunWorkspaceResponse)
def get_run_workspace(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    project = db.get(Project, run.project_id)
    workflow_query = db.query(WorkflowDefinition).filter_by(
        tenant_id=principal.tenant_id,
        workflow_id=run.workflow_id,
    )
    pinned_version = str((run.context_manifest_json or {}).get("workflow_version") or "")
    if pinned_version:
        workflow_query = workflow_query.filter(WorkflowDefinition.version == pinned_version)
    workflow = workflow_query.order_by(WorkflowDefinition.created_at.desc()).first()
    events = (
        db.query(AgentEvent)
        .filter_by(run_id=run_id, tenant_id=principal.tenant_id)
        .order_by(AgentEvent.created_at.desc())
        .limit(50)
        .all()
    )
    packages = db.query(HomologationPackage).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HomologationPackage.created_at.desc()).all()
    reports = db.query(HomologationReport).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HomologationReport.created_at.desc()).all()
    approvals = db.query(ApprovalRequest).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(ApprovalRequest.created_at.desc()).all()
    steps = db.query(AgentStepExecution).filter_by(
        run_id=run_id,
        tenant_id=principal.tenant_id,
    ).order_by(AgentStepExecution.started_at.asc()).all()
    execution_units = db.query(ExecutionUnit).filter_by(
        run_id=run_id, tenant_id=principal.tenant_id
    ).order_by(ExecutionUnit.created_at.asc(), ExecutionUnit.order_index.asc()).all()
    artifact_fragments = db.query(ArtifactFragment).filter_by(
        run_id=run_id, tenant_id=principal.tenant_id
    ).order_by(ArtifactFragment.created_at.asc(), ArtifactFragment.order_index.asc()).all()
    plugin_invocations = db.query(PluginInvocation).filter_by(
        run_id=run_id, tenant_id=principal.tenant_id
    ).order_by(PluginInvocation.created_at.asc()).all()
    return {
        "run": {**model_to_dict(run), "project": model_to_dict(project) if project else None},
        "topology": serialize_workflow_topology(workflow) if workflow else None,
        "nodes": models_to_dict(db.query(WorkflowNodeState).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(WorkflowNodeState.started_at.asc()).all()),
        "agent_states": models_to_dict(db.query(AgentRunState).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentRunState.created_at.asc()).all()),
        "work_items": models_to_dict(db.query(AgentWorkItem).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentWorkItem.created_at.asc()).all()),
        "recent_events": models_to_dict(list(reversed(events))),
        "gates": models_to_dict(db.query(QualityGate).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(QualityGate.created_at.asc()).all()),
        "homologation": {
            "reports": models_to_dict(reports),
            "packages": models_to_dict(packages),
            "approvals": models_to_dict(approvals),
        },
        "counts": {
            "artifacts": db.query(Artifact).filter_by(run_id=run_id, tenant_id=principal.tenant_id).count(),
            "files": db.query(FileChange).filter_by(run_id=run_id, tenant_id=principal.tenant_id).count(),
            "tests": db.query(TestReport).filter_by(run_id=run_id, tenant_id=principal.tenant_id).count(),
            "requirements": db.query(Requirement).filter_by(run_id=run_id, tenant_id=principal.tenant_id).count(),
        },
        "ai": {
            "generation_mode": run.generation_mode,
            "executor_protocol_version": run.executor_protocol_version,
            "trace_id": run.trace_id,
            "last_heartbeat_at": run.last_heartbeat_at.isoformat() if run.last_heartbeat_at else None,
            "budget_usd": run.ai_budget_usd,
            "cost_usd": run.ai_cost_usd,
            "within_budget": float(run.ai_cost_usd or 0) <= float(run.ai_budget_usd or 0),
            "model_calls": db.query(ModelCall).filter_by(run_id=run_id, tenant_id=principal.tenant_id).count(),
        },
        "step_executions": models_to_dict(steps),
        "execution_units": models_to_dict(execution_units),
        "artifact_fragments": models_to_dict(artifact_fragments),
        "plugin_invocations": models_to_dict(plugin_invocations),
        "validation": _validation_manifest(db, run),
    }


def _validation_manifest(db: Session, run: WorkflowRun) -> dict:
    steps = db.query(AgentStepExecution).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(AgentStepExecution.started_at.asc()).all()
    calls = db.query(ModelCall).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(ModelCall.created_at.asc()).all()
    artifacts = db.query(Artifact).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(Artifact.created_at.asc()).all()
    changes = db.query(FileChange).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(FileChange.created_at.asc()).all()
    reports = db.query(TestReport).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(TestReport.created_at.asc()).all()
    traces = (
        db.query(RequirementTrace)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(RequirementTrace.created_at.asc())
        .all()
    )
    gates = db.query(QualityGate).filter_by(tenant_id=run.tenant_id, run_id=run.id).order_by(QualityGate.created_at.asc()).all()
    plugin_invocations = db.query(PluginInvocation).filter_by(
        tenant_id=run.tenant_id, run_id=run.id
    ).order_by(PluginInvocation.created_at.asc()).all()
    linked_artifacts = all(artifact.model_call_id and artifact.step_execution_id for artifact in artifacts) if artifacts else False
    generated_changes = [change for change in changes if change.file_path.startswith("generated_app/")]
    linked_files = all(change.model_call_id and change.step_execution_id for change in generated_changes) if generated_changes else False
    ai_nodes = sorted({step.node_id for step in steps if step.model_call_id})
    completed_ai_nodes = {step.node_id for step in steps if step.model_call_id and step.status == "completed"}
    commands = {report.command: report.status for report in reports}
    initialization_commands = [
        'python -c "from generated_app.backend.app.main import app; assert app"',
        "npm --prefix generated_app/frontend run build",
    ]
    fingerprint_input = "\n".join(
        f"{change.file_path}:{hashlib.sha256(change.after_content.encode()).hexdigest()}"
        for change in generated_changes
    )
    required_plugin_commands = {
        "ponytail": {"activate", "instructions", "review", "audit", "debt", "gain", "help"},
        "cavekit": {"grill", "spec", "research", "review", "build", "check", "backprop", "deepen", "caveman"},
    }
    observed_plugin_commands = {
        name: {
            row.command
            for row in plugin_invocations
            if row.plugin_name == name and row.status in {"completed", "not_applicable"}
        }
        for name in required_plugin_commands
    }
    cavekit_invocations = [row for row in plugin_invocations if row.plugin_name == "cavekit"]

    def cavekit_attempt_key(row: PluginInvocation) -> tuple[str, str, int, str, str]:
        return (
            row.command,
            row.node_id,
            int((row.metadata_json or {}).get("iteration") or 0),
            row.action.split(":", 1)[0],
            row.execution_unit_id or "",
        )

    cavekit_successes = {
        cavekit_attempt_key(row)
        for row in cavekit_invocations
        if row.status in {"completed", "not_applicable"}
    }
    unrecovered_cavekit_failures = {
        cavekit_attempt_key(row)
        for row in cavekit_invocations
        if row.status == "failed"
    }.difference(cavekit_successes)

    def cavekit_evidence_is_valid(row: PluginInvocation) -> bool:
        metadata = row.metadata_json or {}
        if row.status == "completed":
            return bool(
                metadata.get("evidence_type")
                and any(
                    metadata.get(key)
                    for key in ("step_execution_id", "execution_unit_id", "test_report_ids", "quality_gate_ids")
                )
            )
        if row.status == "not_applicable":
            return bool(metadata.get("reason"))
        if row.status == "failed":
            return bool(metadata.get("evidence_type") and row.error)
        return False

    cavekit_stage_evidence_complete = bool(cavekit_invocations) and all(
        cavekit_evidence_is_valid(row) for row in cavekit_invocations
    ) and not unrecovered_cavekit_failures
    plugins_required = str((run.context_manifest_json or {}).get("workflow_version") or "") in {"2.13.2", "2.14.0"}
    plugin_coverage_ok = all(
        commands.issubset(observed_plugin_commands.get(name, set()))
        for name, commands in required_plugin_commands.items()
    ) and all(
        row.status != "failed" for row in plugin_invocations if row.plugin_name == "ponytail"
    ) and cavekit_stage_evidence_complete
    return {
        "run_id": run.id,
        "tenant_id": run.tenant_id,
        "workflow_id": run.workflow_id,
        "generation_mode": run.generation_mode,
        "executor_protocol_version": run.executor_protocol_version,
        "trace_id": run.trace_id,
        "budget": {
            "limit_usd": run.ai_budget_usd,
            "actual_usd": run.ai_cost_usd,
            "within_budget": float(run.ai_cost_usd or 0) <= float(run.ai_budget_usd or 0),
        },
        "ai_nodes": ai_nodes,
        "steps": [
            {
                "id": step.id,
                "node_id": step.node_id,
                "phase": step.phase,
                "iteration": step.iteration,
                "attempt": step.attempt,
                "status": step.status,
                "decision": step.decision,
                "model_call_id": step.model_call_id,
                "prompt_version_id": step.prompt_version_id,
                "input_hash": step.input_hash,
                "output_hash": step.output_hash,
                "output_refs": step.output_refs_json,
            }
            for step in steps
        ],
        "model_calls": [
            {
                "id": call.id,
                "node_state_id": call.workflow_node_state_id,
                "agent_name": call.agent_name,
                "model": call.model_name,
                "model_role": call.model_role,
                "status": call.status,
                "input_hash": call.input_hash,
                "output_hash": call.output_hash,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "cache_creation_tokens": call.cache_creation_tokens,
                "cache_eligible_tokens": call.cache_eligible_tokens,
                "cache_write_tokens": call.cache_write_tokens,
                "cache_savings_usd": call.cache_savings_usd,
                "prompt_cache_key": call.prompt_cache_key or None,
                "provider_route": call.provider_route or None,
                "provider_request_id": call.provider_request_id or None,
                "finish_reason": call.finish_reason or None,
                "execution_unit_id": call.execution_unit_id,
                "trace_id": call.trace_id or None,
                "max_output_tokens": call.max_output_tokens,
                "cost_usd": call.estimated_cost_usd,
                "output_refs": call.output_refs_json,
            }
            for call in calls
        ],
        "plugin_invocations": [
            {
                "id": invocation.id,
                "plugin_name": invocation.plugin_name,
                "plugin_version": invocation.plugin_version,
                "source_revision": invocation.source_revision,
                "command": invocation.command,
                "mode": invocation.mode,
                "node_id": invocation.node_id,
                "action": invocation.action,
                "status": invocation.status,
                "input_hash": invocation.input_hash,
                "output_hash": invocation.output_hash,
                "execution_unit_id": invocation.execution_unit_id,
            }
            for invocation in plugin_invocations
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "name": artifact.name,
                "model_call_id": artifact.model_call_id,
                "step_execution_id": artifact.step_execution_id,
                "sha256": hashlib.sha256(artifact.content.encode()).hexdigest(),
            }
            for artifact in artifacts
        ],
        "generated_files": [
            {
                "id": change.id,
                "path": change.file_path,
                "model_call_id": change.model_call_id,
                "step_execution_id": change.step_execution_id,
                "spec_refs": change.spec_refs_json,
                "sha256": hashlib.sha256(change.after_content.encode()).hexdigest(),
            }
            for change in generated_changes
        ],
        "generation_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest() if fingerprint_input else None,
        "test_reports": [
            {
                "id": report.id,
                "command": report.command,
                "status": report.status,
                "sandbox_execution_id": report.sandbox_execution_id,
                "spec_refs": report.spec_refs_json,
            }
            for report in reports
        ],
        "traceability": [
            {
                "id": trace.id,
                "requirement_id": trace.requirement_id,
                "criterion_ids": trace.criterion_ids_json,
                "invariant_ids": trace.invariant_ids_json,
                "file_path": trace.file_path,
                "test_name": trace.test_name,
                "test_report_id": trace.test_report_id,
                "provenance": trace.provenance,
                "status": trace.status,
            }
            for trace in traces
        ],
        "gates": [{"gate_id": gate.gate_id, "status": gate.status, "score": gate.score} for gate in gates],
        "invariants": {
            "no_failed_model_calls": bool(calls) and all(call.status == "success" for call in calls),
            "model_usage_recorded": bool(calls) and all(
                call.prompt_tokens > 0 and call.completion_tokens > 0 and call.estimated_cost_usd > 0 for call in calls
            ),
            "artifacts_linked_to_model": linked_artifacts,
            "generated_files_linked_to_model": linked_files,
            "tests_are_sandbox_backed": bool(reports) and all(report.sandbox_execution_id for report in reports),
            "all_non_human_steps_have_model_call": bool(steps) and all(step.model_call_id for step in steps),
            "all_ai_workflow_nodes_completed": AI_NATIVE_REQUIRED_NODES.issubset(completed_ai_nodes),
            "generated_application_initializes": all(commands.get(command) == "passed" for command in initialization_commands),
            "ai_native_workflow_only": run.workflow_id == "software_factory_ai_native_v2" and run.generation_mode == "ai_native_v2",
            "mandatory_plugin_coverage": plugin_coverage_ok if plugins_required else True,
            "cavekit_stage_evidence_complete": cavekit_stage_evidence_complete if plugins_required else True,
            "verified_contract_traceability": (
                any(gate.gate_id == "traceability" and gate.status == "passed" for gate in gates)
                and bool(traces)
                and all(trace.provenance == "verified_contract" for trace in traces)
            ) if plugins_required else True,
        },
    }


@router.get("/{run_id}/token-analysis", response_model=TokenAnalysisResponse)
def get_token_analysis(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    steps = (
        db.query(AgentStepExecution)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(AgentStepExecution.started_at.asc())
        .all()
    )
    calls = (
        db.query(ModelCall)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(ModelCall.created_at.asc())
        .all()
    )
    contexts = (
        db.query(ContextBuild)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(ContextBuild.created_at.asc())
        .all()
    )
    calls_by_id = {call.id: call for call in calls}
    contexts_by_step = {context.step_execution_id: context for context in contexts}
    invocation_ids = {call.ai_invocation_id for call in calls if call.ai_invocation_id}
    invocations = (
        db.query(AIInvocation)
        .filter(AIInvocation.tenant_id == run.tenant_id, AIInvocation.id.in_(invocation_ids))
        .all()
        if invocation_ids
        else []
    )
    invocations_by_id = {invocation.id: invocation for invocation in invocations}
    execution_units = db.query(ExecutionUnit).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
    units_by_id = {unit.id: unit for unit in execution_units}
    nodes = []
    represented_call_ids: set[str] = set()
    for step in steps:
        call = calls_by_id.get(step.model_call_id or "")
        if call:
            represented_call_ids.add(call.id)
        unit = units_by_id.get(call.execution_unit_id or "") if call else None
        context = contexts_by_step.get(step.id)
        invocation = invocations_by_id.get(call.ai_invocation_id or "") if call else None
        selected_refs = context.selected_references_json if context else []
        cited_ids = set(context.cited_references_json or []) if context else set()
        if context and not cited_ids:
            cited_ids = set((step.output_manifest_json or {}).get("citations") or [])
        cited_tokens = (
            context.cited_tokens
            if context and context.cited_tokens
            else sum(int(ref.get("estimated_tokens") or 0) for ref in selected_refs if ref.get("ref_id") in cited_ids)
        )
        nodes.append(
            {
                "node_id": step.node_id,
                "iteration": step.iteration,
                "attempt": step.attempt,
                "status": step.status,
                "model": call.model_name if call else None,
                "model_role": call.model_role if call else None,
                "prompt_tokens": call.prompt_tokens if call else 0,
                "completion_tokens": call.completion_tokens if call else 0,
                "cache_read_tokens": call.cache_read_tokens if call else 0,
                "cache_creation_tokens": call.cache_creation_tokens if call else 0,
                "cache_eligible_tokens": call.cache_eligible_tokens if call else 0,
                "cache_write_tokens": call.cache_write_tokens if call else 0,
                "cache_savings_usd": call.cache_savings_usd if call else 0.0,
                "max_output_tokens": call.max_output_tokens if call else 0,
                "cost_usd": call.estimated_cost_usd if call else 0.0,
                "latency_seconds": call.duration_seconds if call else 0.0,
                "ai_invocation_id": call.ai_invocation_id if call else None,
                "execution_unit_id": call.execution_unit_id if call else None,
                "unit_key": unit.unit_key if unit else None,
                "finish_reason": call.finish_reason if call else "",
                "provider_route": call.provider_route if call else "",
                "retry_classification": call.retry_classification if call else "",
                "routing_reason": call.routing_reason if call else "",
                "projected_cost_usd": call.projected_cost_usd if call else 0.0,
                "output_utilization": (
                    round(call.completion_tokens / call.max_output_tokens, 4)
                    if call and call.max_output_tokens
                    else None
                ),
                "budget": (
                    {
                        "soft_usd": invocation.soft_budget_usd,
                        "hard_usd": invocation.hard_budget_usd,
                        "reserved_usd": invocation.reserved_budget_usd,
                    }
                    if invocation
                    else None
                ),
                "context": {
                    "policy_version": context.policy_version if context else None,
                    "budget_tokens": context.input_budget_tokens if context else None,
                    "selected_tokens": context.selected_tokens if context else None,
                    "discarded_tokens": context.discarded_tokens if context else None,
                    "unit_mode": (unit.context_manifest_json or {}).get("mode") if unit else None,
                    "unit_source_tokens": unit.source_input_tokens if unit else None,
                    "unit_input_tokens": unit.estimated_input_tokens if unit else None,
                    "unit_saved_tokens": unit.saved_input_tokens if unit else None,
                    "references": selected_refs,
                    "discarded_references": context.discarded_references_json if context else [],
                    "cited_references": sorted(cited_ids),
                    "cited_tokens": cited_tokens,
                    "selected_not_cited_tokens": max(0, int(context.selected_tokens or 0) - cited_tokens) if context else None,
                },
            }
        )
    for call in calls:
        if call.id in represented_call_ids:
            continue
        unit = units_by_id.get(call.execution_unit_id or "")
        invocation = invocations_by_id.get(call.ai_invocation_id or "")
        unit_references = list((unit.context_manifest_json or {}).get("reference_manifest") or []) if unit else []
        nodes.append(
            {
                "node_id": unit.node_id if unit else call.agent_name,
                "iteration": unit.iteration if unit else 1,
                "attempt": call.attempt_number,
                "status": call.status,
                "model": call.model_name,
                "model_role": call.model_role,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "cache_creation_tokens": call.cache_creation_tokens,
                "cache_eligible_tokens": call.cache_eligible_tokens,
                "cache_write_tokens": call.cache_write_tokens,
                "cache_savings_usd": call.cache_savings_usd,
                "max_output_tokens": call.max_output_tokens,
                "cost_usd": call.estimated_cost_usd,
                "latency_seconds": call.duration_seconds,
                "ai_invocation_id": call.ai_invocation_id,
                "execution_unit_id": call.execution_unit_id,
                "unit_key": unit.unit_key if unit else None,
                "finish_reason": call.finish_reason,
                "provider_route": call.provider_route,
                "retry_classification": call.retry_classification,
                "routing_reason": call.routing_reason,
                "projected_cost_usd": call.projected_cost_usd,
                "output_utilization": round(call.completion_tokens / call.max_output_tokens, 4) if call.max_output_tokens else None,
                "budget": (
                    {
                        "soft_usd": invocation.soft_budget_usd,
                        "hard_usd": invocation.hard_budget_usd,
                        "reserved_usd": invocation.reserved_budget_usd,
                    }
                    if invocation
                    else None
                ),
                "context": {
                    "policy_version": unit.optimization_policy_version if unit else None,
                    "budget_tokens": unit.input_budget_tokens if unit else None,
                    "selected_tokens": unit.estimated_input_tokens if unit else None,
                    "discarded_tokens": None,
                    "unit_mode": (unit.context_manifest_json or {}).get("mode") if unit else None,
                    "unit_source_tokens": unit.source_input_tokens if unit else None,
                    "unit_input_tokens": unit.estimated_input_tokens if unit else None,
                    "unit_saved_tokens": unit.saved_input_tokens if unit else None,
                    "references": [
                        {**reference, "estimated_tokens": 0}
                        for reference in unit_references
                    ],
                    "discarded_references": [],
                    "cited_references": [],
                    "cited_tokens": None,
                    "selected_not_cited_tokens": None,
                },
            }
        )
    prompt_tokens = sum(call.prompt_tokens for call in calls)
    completion_tokens = sum(call.completion_tokens for call in calls)
    cache_read_tokens = sum(call.cache_read_tokens for call in calls)
    total_max_output = sum(call.max_output_tokens for call in calls if call.max_output_tokens)
    retry_calls = [call for call in calls if call.attempt_number > 1 or call.retry_classification not in {"", "initial"}]
    actual_cost = round(sum(call.estimated_cost_usd for call in calls), 8)
    run_budget = float(run.ai_budget_usd or get_settings().model_run_budget_usd)
    compact_source_tokens = sum(unit.source_input_tokens for unit in execution_units if unit.optimization_policy_version)
    compact_input_tokens = sum(unit.estimated_input_tokens for unit in execution_units if unit.optimization_policy_version)
    compact_saved_tokens = sum(unit.saved_input_tokens for unit in execution_units if unit.optimization_policy_version)
    return {
        "run_id": run.id,
        "workflow_id": run.workflow_id,
        "totals": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cache_read_tokens": cache_read_tokens,
            "context_selected_tokens": sum(context.selected_tokens for context in contexts),
            "context_discarded_tokens": sum(context.discarded_tokens for context in contexts),
            "cost_usd": round(sum(call.estimated_cost_usd for call in calls), 8),
            "latency_seconds": round(sum(call.duration_seconds for call in calls), 3),
            "retries": sum(1 for step in steps if step.attempt > 1),
        },
        "provenance": {
            "provider_usage": "real",
            "cost": "real",
            "context_selection": "calculated",
            "discarded_context": "calculated",
        },
        "efficiency": {
            "output_utilization": round(completion_tokens / total_max_output, 4) if total_max_output else None,
            "retry_cost_usd": round(sum(call.estimated_cost_usd for call in retry_calls), 8),
            "retry_tokens": sum(call.prompt_tokens + call.completion_tokens for call in retry_calls),
            "context_cited_tokens": sum(int(context.cited_tokens or 0) for context in contexts),
            "context_selected_not_cited_tokens": sum(
                max(0, int(context.selected_tokens or 0) - int(context.cited_tokens or 0)) for context in contexts
            ),
            "projected_cost_usd": round(sum(call.projected_cost_usd for call in calls), 8),
            "actual_cache_read_tokens": cache_read_tokens,
            "cache_eligible_tokens": sum(call.cache_eligible_tokens for call in calls),
            "cache_write_tokens": sum(call.cache_write_tokens for call in calls),
            "cache_savings_usd": round(sum(call.cache_savings_usd for call in calls), 8),
            "compact_source_tokens": compact_source_tokens,
            "compact_input_tokens": compact_input_tokens,
            "compact_saved_tokens": compact_saved_tokens,
            "compact_savings_ratio": (
                round(compact_saved_tokens / compact_source_tokens, 4) if compact_source_tokens else None
            ),
        },
        "budget": {
            "hard_limit_usd": run_budget,
            "actual_cost_usd": actual_cost,
            "remaining_usd": round(max(0.0, run_budget - actual_cost), 8),
            "reserved_usd": round(max((invocation.reserved_budget_usd for invocation in invocations), default=0.0), 8),
        },
        "nodes": nodes,
    }


@router.get("/{run_id}/validation-manifest")
def get_validation_manifest(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    return _validation_manifest(db, run)


@router.get("/{run_id}/plugins", response_model=RunPluginAnalysisResponse)
def get_run_plugins(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    invocations = (
        db.query(PluginInvocation)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(PluginInvocation.created_at.asc())
        .all()
    )
    changes = (
        db.query(FileChange)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .filter(FileChange.file_path.like("generated_app/%"))
        .order_by(FileChange.created_at.asc())
        .all()
    )
    latest_by_path = {change.file_path: change.after_content for change in changes}
    dependencies: set[str] = set()
    for path, content in latest_by_path.items():
        if path.endswith("package.json"):
            try:
                package = json.loads(content)
                dependencies.update((package.get("dependencies") or {}).keys())
                dependencies.update((package.get("devDependencies") or {}).keys())
            except (TypeError, ValueError):
                pass
        if path.endswith(("requirements.txt", "requirements.in")):
            dependencies.update(
                line.split("==", 1)[0].split(">=", 1)[0].strip()
                for line in content.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
    artifacts = (
        db.query(Artifact)
        .filter(
            Artifact.tenant_id == run.tenant_id,
            Artifact.run_id == run.id,
            Artifact.name.in_(["PONYTAIL_AUDIT.md", "PONYTAIL_DEBT.md"]),
        )
        .order_by(Artifact.created_at.asc())
        .all()
    )
    commands = sorted({f"{row.plugin_name}.{row.command}" for row in invocations})
    return {
        "run_id": run.id,
        "policy_version": str((run.context_manifest_json or {}).get("workflow_version") or ""),
        "manifests": FactoryPluginRuntime().manifests(),
        "help": PonytailPolicy.help_payload(),
        "invocations": models_to_dict(invocations),
        "coverage": {
            "commands": commands,
            "completed": sum(row.status == "completed" for row in invocations),
            "registered": sum(row.status == "registered" for row in invocations),
            "not_applicable": sum(row.status == "not_applicable" for row in invocations),
            "failed": sum(row.status == "failed" for row in invocations),
        },
        "measured": {
            "generated_files": len(latest_by_path),
            "non_blank_lines": sum(
                1 for content in latest_by_path.values() for line in content.splitlines() if line.strip()
            ),
            "declared_dependencies": len(dependencies),
            "dependency_names": sorted(dependencies),
            "model_cost_usd": float(run.ai_cost_usd or 0.0),
            "provenance": "calculated_from_persisted_run",
        },
        "artifacts": [
            {
                "id": artifact.id,
                "name": artifact.name,
                "evidence_classification": artifact.evidence_classification,
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in artifacts
        ],
        "benchmark_boundary": "No upstream Ponytail benchmark is presented as savings for this run.",
    }


@router.get("/{run_id}/execution-units")
def get_execution_units(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    units = (
        db.query(ExecutionUnit)
        .filter_by(tenant_id=run.tenant_id, run_id=run.id)
        .order_by(ExecutionUnit.created_at.asc(), ExecutionUnit.order_index.asc())
        .all()
    )
    return {
        "run_id": run.id,
        "executor_protocol_version": run.executor_protocol_version,
        "trace_id": run.trace_id or None,
        "units": models_to_dict(units),
    }


@router.get("/{run_id}/reliability")
def get_run_reliability(
    run_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    units = db.query(ExecutionUnit).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
    completed = [unit for unit in units if unit.status == "completed"]
    calls = db.query(ModelCall).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
    return {
        "run_id": run.id,
        "executor_protocol_version": run.executor_protocol_version,
        "checkpoint": {"phase": run.current_phase, "node": run.current_node, "status": run.status},
        "trace_id": run.trace_id or None,
        "last_heartbeat_at": run.last_heartbeat_at.isoformat() if run.last_heartbeat_at else None,
        "units": {
            "total": len(units),
            "completed": len(completed),
            "running": sum(unit.status == "running" for unit in units),
            "pending": sum(unit.status == "pending" for unit in units),
            "failed": sum(unit.status == "failed" for unit in units),
            "recovered": sum(unit.status == "completed" and unit.attempt_count > 1 for unit in units),
            "retries": sum(max(0, unit.attempt_count - 1) for unit in units),
            "continuations": sum(unit.continuation_count for unit in units),
        },
        "model_calls": {
            "total": len(calls),
            "errors": sum(call.status != "success" for call in calls),
            "timeouts": sum(call.retry_classification == "transient" and "timeout" in (call.error or "").casefold() for call in calls),
        },
        "invariants": {
            "confirmed_outputs_have_hashes": all(unit.output_hash for unit in completed),
            "confirmed_outputs_have_model_provenance": all(unit.model_call_id for unit in completed),
            "rpo_zero_for_confirmed_units": all(unit.output_hash and unit.model_call_id for unit in completed),
        },
    }


@router.post("/{run_id}/pause")
async def pause_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    if _uses_temporal():
        _require_temporal_workflow(run)
    run.status = "pending"
    control = provider.control_state(db, run)
    control.status = "paused"
    control.current_sop_step = "operator_paused"
    if _uses_temporal():
        enqueue_signal(
            db,
            run,
            signal_name="operator_control",
            payload={"action": "pause"},
            decision_key=f"operator-pause:{uuid.uuid4()}",
        )
    audit(db, principal, "run.paused", "run", run.id)
    db.commit()
    return model_to_dict(run)


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    if _uses_temporal():
        _require_temporal_workflow(run)
    acquire_workflow_slot(db, run.id)
    run.status = "running"
    if run.current_phase == "budget_paused":
        run.current_phase = "budget_resumed"
    control = provider.control_state(db, run)
    control.status = "running"
    control.current_sop_step = "continuous"
    if _uses_temporal():
        enqueue_signal(
            db,
            run,
            signal_name="operator_control",
            payload={"action": "resume"},
            decision_key=f"operator-resume:{uuid.uuid4()}",
        )
    audit(db, principal, "run.resumed", "run", run.id)
    db.commit()
    return model_to_dict(run)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    if run.status == "cancel_requested":
        if not _uses_temporal():
            raise HTTPException(status_code=409, detail="Cancellation is already pending")
        _require_temporal_workflow(run)
        enqueue_cancel(db, run)
        audit(db, principal, "run.cancellation_reconciled", "run", run.id)
        db.commit()
        db.refresh(run)
        return model_to_dict(run)
    _ensure_controllable(run)
    previous_status = run.status
    if _uses_temporal():
        _require_temporal_workflow(run)
    control = provider.control_state(db, run)
    if _uses_temporal():
        enqueue_cancel(db, run)
    if previous_status == "waiting_for_human":
        # The execution activity already returned before the approval wait, so
        # there is no provider thread left to acknowledge this cancellation.
        control.status = "cancelled"
        control.current_sop_step = "cancelled_at_human_wait"
        run.status = "cancelled"
        run.current_phase = "cancelled"
        run.current_node = "FINAL"
        run.finished_at = utcnow()
        release_workflow_slot(db, run.id)
        audit(db, principal, "run.cancelled", "run", run.id, {"previous_status": previous_status})
    else:
        control.status = "cancel_requested"
        control.current_sop_step = "operator_cancel_requested"
        run.status = "cancel_requested"
        audit(db, principal, "run.cancel_requested", "run", run.id, {"previous_status": previous_status})
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.post("/{run_id}/step")
async def step_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    if _uses_temporal():
        _require_temporal_workflow(run)
        control = provider.control_state(db, run)
        control.status = "step_once"
        control.current_sop_step = "manual_step_requested"
        run.status = "running"
    else:
        run = provider.step_run(db, run_id)
    audit(db, principal, "run.step_requested", "run", run.id)
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.post("/{run_id}/approve")
async def approve_run(
    run_id: str,
    payload: HumanDecision = HumanDecision(),
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    if _uses_temporal():
        _require_temporal_workflow(run)
    run = provider.approve_run(db, run_id, payload.comment, commit=False)
    if _uses_temporal():
        enqueue_signal(
            db,
            run,
            signal_name="human_decision",
            payload={"decision": "approved"},
            decision_key="approved",
        )
    audit(db, principal, "run.approved", "run", run.id)
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.post("/{run_id}/reject")
async def reject_run(
    run_id: str,
    payload: HumanDecision = HumanDecision(),
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    if _uses_temporal():
        _require_temporal_workflow(run)
    run = provider.reject_run(db, run_id, payload.comment, commit=False)
    if _uses_temporal():
        enqueue_signal(
            db,
            run,
            signal_name="human_decision",
            payload={"decision": "rejected"},
            decision_key="rejected",
        )
    audit(db, principal, "run.rejected", "run", run.id)
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.post("/{run_id}/request-changes")
async def request_changes(
    run_id: str,
    payload: HumanDecision = HumanDecision(),
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    run = provider.request_changes(db, run.id, payload.comment, commit=False)
    if _uses_temporal():
        _require_temporal_workflow(run)
        enqueue_signal(
            db,
            run,
            signal_name="human_decision",
            payload={"decision": "changes_requested", "comment": payload.comment},
            decision_key=f"changes_requested:{run.id}:{run.updated_at.isoformat()}",
        )
    audit(db, principal, "run.changes_requested", "run", run.id, {"comment": payload.comment})
    db.commit()
    db.refresh(run)
    if not _uses_temporal() and hasattr(provider, "resume_ai_native_rework"):
        provider.resume_ai_native_rework(run.id, run.tenant_id)
    return model_to_dict(run)


@router.get("/{run_id}/events")
def get_events(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AgentEvent).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentEvent.created_at.asc()).all())


@router.get("/{run_id}/stream")
async def stream_events(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return StreamingResponse(event_stream(SessionLocal, run_id, tenant_id=principal.tenant_id), media_type="text/event-stream")


@router.get("/{run_id}/nodes")
def get_nodes(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(WorkflowNodeState).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(WorkflowNodeState.started_at.asc()).all())


@router.get("/{run_id}/agent-states")
def get_agent_states(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AgentRunState).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentRunState.created_at.asc()).all())


@router.get("/{run_id}/agent-messages")
def get_agent_messages(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AgentMessage).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentMessage.created_at.asc()).all())


@router.get("/{run_id}/work-items")
def get_work_items(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AgentWorkItem).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentWorkItem.created_at.asc()).all())


@router.get("/{run_id}/artifacts")
def get_artifacts(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(Artifact).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(Artifact.created_at.asc()).all())


@router.get("/{run_id}/artifacts/{artifact_id}")
def get_artifact(run_id: str, artifact_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    artifact = db.query(Artifact).filter_by(run_id=run_id, tenant_id=principal.tenant_id, id=artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return model_to_dict(artifact)


@router.get("/{run_id}/files")
def get_files(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    changes = db.query(FileChange).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(FileChange.created_at.asc()).all()
    latest = {}
    for change in changes:
        latest[change.file_path] = model_to_dict(change)
    return list(latest.values())


@router.get("/{run_id}/files/content", response_class=PlainTextResponse)
def get_file_content(
    run_id: str,
    path: str = Query(...),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _get_run_or_404(db, run_id, principal)
    try:
        return provider.read_workspace_file(run_id, path, principal.tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{run_id}/diffs")
def get_diffs(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(FileChange).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(FileChange.created_at.asc()).all())


@router.get("/{run_id}/test-reports")
def get_test_reports(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(TestReport).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(TestReport.created_at.asc()).all())


@router.get("/{run_id}/requirements")
def get_requirements(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(Requirement).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(Requirement.requirement_id.asc()).all())


@router.get("/{run_id}/acceptance-criteria")
def get_acceptance_criteria(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AcceptanceCriterion).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AcceptanceCriterion.criterion_id.asc()).all())


@router.get("/{run_id}/traceability")
def get_traceability(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(RequirementTrace).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(RequirementTrace.requirement_id.asc()).all())


@router.get("/{run_id}/quality-gates")
def get_quality_gates(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(QualityGate).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(QualityGate.created_at.asc()).all())


@router.get("/{run_id}/homologation")
def get_homologation(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    reports = models_to_dict(db.query(HomologationReport).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HomologationReport.created_at.desc()).all())
    packages = models_to_dict(db.query(HomologationPackage).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HomologationPackage.created_at.desc()).all())
    scores = models_to_dict(db.query(QualityScore).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(QualityScore.created_at.asc()).all())
    approvals = models_to_dict(db.query(ApprovalRequest).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(ApprovalRequest.created_at.desc()).all())
    return {"reports": reports, "packages": packages, "scores": scores, "approvals": approvals}


@router.get("/{run_id}/delivery-package")
def get_delivery_package(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    package = db.query(HomologationPackage).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HomologationPackage.created_at.desc()).first()
    if not package:
        raise HTTPException(status_code=404, detail="Delivery package not found")
    return model_to_dict(package)


@router.get("/{run_id}/delivery-package/download")
def download_delivery_package(
    run_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _get_run_or_404(db, run_id, principal)
    package = (
        db.query(HomologationPackage)
        .filter_by(run_id=run_id, tenant_id=principal.tenant_id)
        .order_by(HomologationPackage.created_at.desc())
        .first()
    )
    if not package:
        raise HTTPException(status_code=404, detail="Delivery package not found")

    files = []
    if object_storage.enabled:
        prefix = str((package.manifest_json or {}).get("storage_prefix") or "")
        if not prefix:
            raise HTTPException(status_code=409, detail="Delivery package storage prefix is missing")
        files = list(object_storage.read_prefix(prefix))
    else:
        from pathlib import Path

        root = Path(package.path).resolve()
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="Delivery package directory not found")
        files = [(str(path.relative_to(root)), path.read_bytes()) for path in root.rglob("*") if path.is_file()]
    if not files:
        raise HTTPException(status_code=409, detail="Delivery package has no files")
    if sum(len(content) for _, content in files) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Delivery package exceeds the assisted-pilot download limit")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path, content in files:
            archive_path = relative_path.replace("\\", "/").lstrip("/")
            if not archive_path or ".." in archive_path.split("/"):
                raise HTTPException(status_code=409, detail="Delivery package contains an invalid path")
            archive.writestr(archive_path, content)
    audit(
        db,
        principal,
        "homologation.package_downloaded",
        "homologation_package",
        package.id,
        {"run_id": run_id, "file_count": len(files)},
    )
    db.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="homologation-{run_id}.zip"'},
    )


@router.post("/{run_id}/generate-homologation-package")
def generate_homologation_package(
    run_id: str,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = _get_run_or_404(db, run_id, principal)
    package = (
        db.query(HomologationPackage)
        .filter_by(run_id=run.id, tenant_id=principal.tenant_id)
        .order_by(HomologationPackage.created_at.desc())
        .first()
    )
    if not package:
        raise HTTPException(status_code=409, detail="Homologation package is not ready; complete technical quality gates first")
    audit(db, principal, "homologation.package_requested", "homologation_package", package.id, {"run_id": run.id})
    db.commit()
    return model_to_dict(package)
