from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, get_current_principal, require_roles
from app.db.session import get_db
from app.models import Project
from app.schemas import ProjectCreate
from app.services.project_service import create_project
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("")
def post_project(
    payload: ProjectCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    project = create_project(db, payload.name, payload.description, tenant_id=principal.tenant_id)
    audit(db, principal, "project.created", "project", project.id)
    db.commit()
    db.refresh(project)
    return model_to_dict(project)


@router.get("")
def get_projects(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(Project).filter_by(tenant_id=principal.tenant_id).order_by(Project.created_at.desc()).all())


@router.get("/{project_id}")
def get_project(project_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    project = db.query(Project).filter_by(id=project_id, tenant_id=principal.tenant_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return model_to_dict(project)
