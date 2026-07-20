import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, require_roles
from app.db.session import get_db
from app.core.config import get_settings
from app.models import Batch, BatchItem, BatchMetric, Project, WorkflowRun
from app.services.serialization import model_to_dict, models_to_dict
from app.service_delivery.capacity import acquire_workflow_slot
from app.workflow.temporal_outbox import enqueue_start
from app.schemas import BatchCreate

router = APIRouter(prefix="/batches", tags=["batches"])
get_current_principal = require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")


@router.post("")
async def post_batch(
    payload: BatchCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    project_ids = [item.project_id for item in payload.items]
    projects = db.query(Project).filter(Project.tenant_id == principal.tenant_id, Project.id.in_(project_ids)).all()
    project_by_id = {project.id: project for project in projects}
    missing = sorted(set(project_ids).difference(project_by_id))
    if missing:
        raise HTTPException(status_code=404, detail={"code": "BATCH_PROJECT_NOT_FOUND", "project_ids": missing})
    batch = Batch(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        status="running",
        total_items=len(payload.items),
    )
    db.add(batch)
    db.flush()
    for item in payload.items:
        project = project_by_id[item.project_id]
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            project_id=project.id,
            workflow_id="software_factory_homologation_v1",
            demand=item.demand.strip(),
            status="scheduled",
            current_phase="temporal_scheduled",
            current_node="Temporal Worker",
            provider="production-litellm",
        )
        db.add(run)
        db.flush()
        acquire_workflow_slot(db, run.id)
        enqueue_start(db, run)
        run.status = "temporal_dispatch_pending"
        db.add(
            BatchItem(
                id=str(uuid.uuid4()),
                tenant_id=principal.tenant_id,
                batch_id=batch.id,
                project_id=project.id,
                run_id=run.id,
                demand=item.demand.strip(),
                status=run.status,
                current_phase="temporal_scheduled",
            )
        )
    db.add(BatchMetric(id=str(uuid.uuid4()), tenant_id=principal.tenant_id, batch_id=batch.id, name="scheduled_runs", value=len(payload.items), metadata_json={"source": "operator_request"}))
    audit(db, principal, "batch.created", "batch", batch.id, {"item_count": len(payload.items)})
    db.commit()
    db.refresh(batch)
    return model_to_dict(batch)


@router.get("")
def get_batches(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(Batch).filter_by(tenant_id=principal.tenant_id).order_by(Batch.created_at.desc()).all())


@router.get("/{batch_id}")
def get_batch(batch_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    batch = db.query(Batch).filter_by(id=batch_id, tenant_id=principal.tenant_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return model_to_dict(batch)


@router.post("/{batch_id}/start")
def start_batch(batch_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    batch = db.query(Batch).filter_by(id=batch_id, tenant_id=principal.tenant_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.status = "running"
    db.commit()
    return model_to_dict(batch)


@router.post("/{batch_id}/pause")
def pause_batch(batch_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    batch = db.query(Batch).filter_by(id=batch_id, tenant_id=principal.tenant_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.status = "paused"
    db.commit()
    return model_to_dict(batch)


@router.post("/{batch_id}/resume")
def resume_batch(batch_id: str, principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    batch = db.query(Batch).filter_by(id=batch_id, tenant_id=principal.tenant_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.status = "running"
    db.commit()
    return model_to_dict(batch)


@router.get("/{batch_id}/items")
def get_batch_items(batch_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(BatchItem).filter_by(batch_id=batch_id, tenant_id=principal.tenant_id).order_by(BatchItem.created_at.asc()).all())


@router.get("/{batch_id}/metrics")
def get_batch_metrics(batch_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(BatchMetric).filter_by(batch_id=batch_id, tenant_id=principal.tenant_id).order_by(BatchMetric.created_at.asc()).all())
