from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import yaml

from app.auth.dependencies import Principal, require_roles
from app.db.session import get_db
from app.models import WorkflowDefinition
from app.schemas.operational import WorkflowTopologyResponse
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/workflows", tags=["workflows"])
OPERATIONAL_ROLES = ("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
get_current_principal = require_roles(*OPERATIONAL_ROLES)


def serialize_workflow_topology(workflow: WorkflowDefinition) -> dict:
    document = yaml.safe_load(workflow.yaml_content or "") or {}
    graph = document.get("graph") or {}
    return {
        "workflow_id": workflow.workflow_id,
        "version": workflow.version,
        "name": workflow.name,
        "description": workflow.description,
        "ui": graph.get("ui") or {},
        "phases": graph.get("phases") or [],
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
    }


@router.get("")
def get_workflows(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    provider.ensure_workflows(db, tenant_id=principal.tenant_id)
    return models_to_dict(db.query(WorkflowDefinition).filter_by(tenant_id=principal.tenant_id).order_by(WorkflowDefinition.workflow_id.asc()).all())


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    provider.ensure_workflows(db, tenant_id=principal.tenant_id)
    workflow = db.query(WorkflowDefinition).filter_by(workflow_id=workflow_id, tenant_id=principal.tenant_id).order_by(WorkflowDefinition.created_at.desc()).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return model_to_dict(workflow)


@router.get("/{workflow_id}/topology", response_model=WorkflowTopologyResponse)
def get_workflow_topology(workflow_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    provider.ensure_workflows(db, tenant_id=principal.tenant_id)
    workflow = db.query(WorkflowDefinition).filter_by(workflow_id=workflow_id, tenant_id=principal.tenant_id).order_by(WorkflowDefinition.created_at.desc()).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return serialize_workflow_topology(workflow)
