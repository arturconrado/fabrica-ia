import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, get_current_principal, require_roles
from app.db.session import get_db
from app.models import Batch, BatchItem, BatchMetric, Project, WorkflowRun
from app.providers.temporal_runner import TemporalWorkflowRunner
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("")
async def post_batch(principal: Principal = Depends(require_roles("owner", "admin", "operator")), db: Session = Depends(get_db)):
    batch = Batch(id=str(uuid.uuid4()), tenant_id=principal.tenant_id, name="Enterprise Portfolio Batch", status="running", total_items=3)
    db.add(batch)
    db.flush()
    demands = [
        ("ContractFlow Enterprise", "Crie um sistema para gestão de clientes, contratos e faturas."),
        ("InventoryFlow Enterprise", "Crie um sistema para produtos, estoque e movimentações."),
        ("HelpdeskFlow Enterprise", "Crie um sistema para tickets, prioridades e status."),
    ]
    for name, demand in demands:
        project = Project(id=str(uuid.uuid4()), tenant_id=principal.tenant_id, name=name, description="Batch enterprise build item.")
        db.add(project)
        db.flush()
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
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
        scheduled = await TemporalWorkflowRunner().start_enterprise_run(
            tenant_id=principal.tenant_id,
            demand=demand,
            project_id=project.id,
            run_id=run.id,
        )
        run.status = scheduled.status
        run.temporal_workflow_id = scheduled.workflow_id
        run.temporal_run_id = scheduled.run_id
        db.add(
            BatchItem(
                id=str(uuid.uuid4()),
                tenant_id=principal.tenant_id,
                batch_id=batch.id,
                project_id=project.id,
                run_id=run.id,
                demand=demand,
                status=scheduled.status,
                current_phase="temporal_scheduled",
            )
        )
    db.add(BatchMetric(id=str(uuid.uuid4()), tenant_id=principal.tenant_id, batch_id=batch.id, name="scheduled_runs", value=3, metadata_json={}))
    audit(db, principal, "batch.created", "batch", batch.id)
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
