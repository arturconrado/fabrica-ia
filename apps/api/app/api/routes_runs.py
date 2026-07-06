import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, get_current_principal, require_roles
from app.core.status import APPROVED_FOR_HOMOLOGATION, CANCELLED, FAILED, REJECTED
from app.db.session import SessionLocal, get_db
from app.events.sse import event_stream
from app.models import (
    AcceptanceCriterion,
    AgentMessage,
    AgentRunState,
    AgentEvent,
    AgentWorkItem,
    ApprovalRequest,
    Artifact,
    FileChange,
    HomologationPackage,
    HomologationReport,
    Project,
    QualityGate,
    QualityScore,
    Requirement,
    RequirementTrace,
    TestReport,
    WorkflowNodeState,
    WorkflowRun,
)
from app.schemas import EnterpriseRunCreate, HumanDecision, RunCreate
from app.providers.temporal_runner import TemporalWorkflowRunner
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/runs", tags=["runs"])


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
        "controlled failure/correction evidence, final pytest pass, 17 quality gates, HRS >= 90, "
        "homologation package and human approval checkpoint."
    )


def _get_run_or_404(db: Session, run_id: str, principal: Principal) -> WorkflowRun:
    run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=principal.tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _ensure_controllable(run: WorkflowRun) -> None:
    if run.status in {FAILED, CANCELLED, REJECTED, APPROVED_FOR_HOMOLOGATION}:
        raise HTTPException(status_code=409, detail=f"Run is terminal and cannot be controlled: {run.status}")


def _require_temporal_workflow(run: WorkflowRun) -> None:
    if not run.temporal_workflow_id:
        raise HTTPException(status_code=409, detail="Production-only controls require a Temporal workflow id")


def _create_scheduled_run(
    db: Session,
    *,
    tenant_id: str,
    demand: str,
    project_id: Optional[str] = None,
    project_name: str = "Enterprise Build",
) -> WorkflowRun:
    project = db.query(Project).filter_by(id=project_id, tenant_id=tenant_id).first() if project_id else None
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
    return run


@router.post("")
async def post_run(
    payload: RunCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = _create_scheduled_run(db, tenant_id=principal.tenant_id, demand=payload.demand, project_id=payload.project_id)
    scheduled = await TemporalWorkflowRunner().start_enterprise_run(
        tenant_id=principal.tenant_id,
        demand=payload.demand,
        project_id=run.project_id,
        run_id=run.id,
    )
    run.status = scheduled.status
    run.temporal_workflow_id = scheduled.workflow_id
    run.temporal_run_id = scheduled.run_id
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
    demand = _enterprise_demand(payload)
    run = _create_scheduled_run(
        db,
        tenant_id=principal.tenant_id,
        demand=demand,
        project_name=payload.project_name,
    )
    scheduled = await TemporalWorkflowRunner().start_enterprise_run(
        tenant_id=principal.tenant_id,
        demand=demand,
        project_id=run.project_id,
        run_id=run.id,
    )
    run.status = scheduled.status
    run.temporal_workflow_id = scheduled.workflow_id
    run.temporal_run_id = scheduled.run_id
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
            "temporal_workflow_id": scheduled.workflow_id,
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
def get_run(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    item = model_to_dict(run)
    project = db.get(Project, run.project_id)
    item["project"] = model_to_dict(project) if project else None
    return item


@router.post("/{run_id}/pause")
async def pause_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "operator_control", {"action": "pause"})
    run.status = "pending"
    control = db.query(AgentRunState).filter_by(run_id=run.id, tenant_id=principal.tenant_id, agent_name="RUN_CONTROL").first()
    if control:
        control.status = "paused"
        control.current_sop_step = "operator_paused"
    audit(db, principal, "run.paused", "run", run.id)
    db.commit()
    return model_to_dict(run)


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "operator_control", {"action": "resume"})
    run.status = "running"
    control = db.query(AgentRunState).filter_by(run_id=run.id, tenant_id=principal.tenant_id, agent_name="RUN_CONTROL").first()
    if control:
        control.status = "running"
        control.current_sop_step = "continuous"
    audit(db, principal, "run.resumed", "run", run.id)
    db.commit()
    return model_to_dict(run)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "operator_control", {"action": "cancel"})
    run.status = "cancelled"
    audit(db, principal, "run.cancelled", "run", run.id)
    db.commit()
    return model_to_dict(run)


@router.post("/{run_id}/step")
async def step_run(run_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id, principal)
    _ensure_controllable(run)
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "operator_control", {"action": "step"})
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
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "human_decision", {"decision": "approved", "comment": payload.comment})
    run = provider.approve_run(db, run_id, payload.comment)
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
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "human_decision", {"decision": "rejected", "comment": payload.comment})
    run = provider.reject_run(db, run_id, payload.comment)
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
    _require_temporal_workflow(run)
    await TemporalWorkflowRunner().signal(run.temporal_workflow_id, "human_decision", {"decision": "changes_requested", "comment": payload.comment})
    run = provider.request_changes(db, run_id, payload.comment)
    audit(db, principal, "run.changes_requested", "run", run.id)
    db.commit()
    db.refresh(run)
    return model_to_dict(run)


@router.get("/{run_id}/events")
def get_events(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id, principal)
    return models_to_dict(db.query(AgentEvent).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(AgentEvent.created_at.asc()).all())


@router.get("/{run_id}/stream")
async def stream_events(run_id: str, principal: Principal = Depends(get_current_principal)):
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
        return provider.read_workspace_file(run_id, path)
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
