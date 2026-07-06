from sqlalchemy.orm import Session

from app.models import Project
from app.services.run_service import provider


def create_project(db: Session, name: str, description: str = "", tenant_id: str = "local-dev") -> Project:
    return provider.create_project(db, name, description, tenant_id=tenant_id)
