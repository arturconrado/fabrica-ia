from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, get_current_principal, require_roles
from app.db.session import get_db
from app.models import LearningLesson, RewardSignal
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/lessons")
def get_lessons(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(LearningLesson).filter_by(tenant_id=principal.tenant_id).order_by(LearningLesson.created_at.desc()).all())


@router.post("/lessons/{lesson_id}/approve")
def approve_lesson(
    lesson_id: str,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    lesson = db.query(LearningLesson).filter_by(id=lesson_id, tenant_id=principal.tenant_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    try:
        lesson = provider.approve_lesson(db, lesson_id)
        audit(db, principal, "lesson.approved", "learning_lesson", lesson.id)
        db.commit()
        db.refresh(lesson)
        return model_to_dict(lesson)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lesson not found")


@router.get("/reward-signals")
def get_reward_signals(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(RewardSignal).filter_by(tenant_id=principal.tenant_id).order_by(RewardSignal.created_at.desc()).all())
