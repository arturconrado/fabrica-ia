from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, require_roles
from app.db.session import get_db
from app.models import HumanFeedback, WorkflowRun
from app.schemas import FeedbackCreate
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(tags=["feedback"])
get_current_principal = require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")


@router.post("/feedback")
def post_feedback(
    payload: FeedbackCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    run = db.query(WorkflowRun).filter_by(id=payload.run_id, tenant_id=principal.tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    feedback = provider.create_feedback(
        db,
        run_id=payload.run_id,
        event_id=payload.event_id,
        artifact_id=payload.artifact_id,
        node_id=payload.node_id,
        rating=payload.rating,
        comment=payload.comment,
        feedback_type=payload.feedback_type,
        labels=payload.labels,
        tenant_id=principal.tenant_id,
    )
    audit(db, principal, "feedback.created", "feedback", feedback.id, {"run_id": payload.run_id})
    db.commit()
    db.refresh(feedback)
    return model_to_dict(feedback)


@router.get("/runs/{run_id}/feedback")
def get_run_feedback(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(HumanFeedback).filter_by(run_id=run_id, tenant_id=principal.tenant_id).order_by(HumanFeedback.created_at.desc()).all())
