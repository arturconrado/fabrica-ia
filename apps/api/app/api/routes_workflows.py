from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, get_current_principal
from app.db.session import get_db
from app.models import WorkflowDefinition
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
def get_workflows(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    provider.ensure_workflows(db, tenant_id=principal.tenant_id)
    return models_to_dict(db.query(WorkflowDefinition).filter_by(tenant_id=principal.tenant_id).order_by(WorkflowDefinition.workflow_id.asc()).all())


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    provider.ensure_workflows(db, tenant_id=principal.tenant_id)
    workflow = db.query(WorkflowDefinition).filter_by(workflow_id=workflow_id, tenant_id=principal.tenant_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return model_to_dict(workflow)
