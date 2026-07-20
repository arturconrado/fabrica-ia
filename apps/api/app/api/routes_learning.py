from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, require_roles
from app.db.session import get_db
from app.learning.optimization_service import LearningOptimizationError, LearningOptimizationService
from app.models import LearningCandidate, LearningLesson, LearningPolicy, LearningSignal, RewardSignal
from app.services.run_service import provider
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(prefix="/learning", tags=["learning"])
get_current_principal = require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")
optimization = LearningOptimizationService()


class CandidateProposal(BaseModel):
    title: str = Field(default="", max_length=240)
    target_agents: list[str] = Field(default_factory=list, max_length=20)
    critical_security: bool = False


class CostPolicyProposal(BaseModel):
    title: str = Field(default="", max_length=240)


class CandidateDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=4000)


class RollbackDecision(BaseModel):
    comment: str = Field(min_length=1, max_length=4000)


def _learning_error(exc: LearningOptimizationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


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


@router.get("/signals")
def get_learning_signals(
    agent: str = Query(default="", max_length=160),
    signal_type: str = Query(default="", max_length=160),
    run_id: str = Query(default="", max_length=160),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    query = db.query(LearningSignal).filter_by(tenant_id=principal.tenant_id)
    if agent:
        query = query.filter(LearningSignal.agent_name == agent)
    if signal_type:
        query = query.filter(LearningSignal.signal_type == signal_type)
    if run_id:
        query = query.filter(LearningSignal.run_id == run_id)
    return models_to_dict(query.order_by(LearningSignal.created_at.desc()).limit(500).all())


@router.get("/candidates")
def get_learning_candidates(
    status: str = Query(default="", max_length=80),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    query = db.query(LearningCandidate).filter_by(tenant_id=principal.tenant_id)
    if status:
        query = query.filter(LearningCandidate.status == status)
    return models_to_dict(query.order_by(LearningCandidate.created_at.desc()).all())


@router.post("/lessons/{lesson_id}/propose-global")
def propose_global_candidate(
    lesson_id: str,
    payload: CandidateProposal,
    principal: Principal = Depends(require_roles("owner", "super_admin", "admin")),
    db: Session = Depends(get_db),
):
    try:
        candidate = optimization.propose_global_candidate(
            db,
            tenant_id=principal.tenant_id,
            lesson_id=lesson_id,
            actor_user_id=principal.user_id,
            title=payload.title,
            target_agents=payload.target_agents,
            critical_security=payload.critical_security,
        )
        audit(db, principal, "learning.candidate_proposed", "learning_candidate", candidate.id)
        db.commit()
        db.refresh(candidate)
        return model_to_dict(candidate)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc


@router.post("/cost-policies/proposals")
def propose_cost_policy(
    payload: CostPolicyProposal,
    principal: Principal = Depends(require_roles("owner", "super_admin", "admin")),
    db: Session = Depends(get_db),
):
    try:
        candidate = optimization.propose_cost_policy(
            db,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            title=payload.title,
        )
        audit(db, principal, "learning.cost_policy_proposed", "learning_candidate", candidate.id)
        db.commit()
        db.refresh(candidate)
        return model_to_dict(candidate)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc


@router.post("/candidates/{candidate_id}/evaluate")
def evaluate_candidate(
    candidate_id: str,
    principal: Principal = Depends(require_roles("owner", "super_admin", "admin")),
    db: Session = Depends(get_db),
):
    candidate = db.query(LearningCandidate).filter_by(id=candidate_id, tenant_id=principal.tenant_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    try:
        evaluation = optimization.evaluate_candidate(db, candidate=candidate, actor_user_id=principal.user_id)
        audit(db, principal, "learning.candidate_evaluated", "learning_candidate", candidate.id, {"evaluation_id": evaluation.id})
        db.commit()
        db.refresh(evaluation)
        return model_to_dict(evaluation)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc


@router.post("/candidates/{candidate_id}/decisions")
def decide_candidate(
    candidate_id: str,
    payload: CandidateDecision,
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    candidate = db.query(LearningCandidate).filter_by(id=candidate_id, tenant_id=principal.tenant_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    try:
        candidate = optimization.decide_candidate(
            db,
            candidate=candidate,
            decision=payload.decision,
            comment=payload.comment,
            actor_user_id=principal.user_id,
        )
        audit(db, principal, f"learning.candidate_{candidate.status}", "learning_candidate", candidate.id)
        db.commit()
        db.refresh(candidate)
        return model_to_dict(candidate)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc


@router.get("/policies")
def get_learning_policies(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return models_to_dict(
        db.query(LearningPolicy)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(LearningPolicy.created_at.desc())
        .all()
    )


@router.post("/policies/{policy_id}/rollback")
def rollback_policy(
    policy_id: str,
    payload: RollbackDecision,
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    policy = db.query(LearningPolicy).filter_by(id=policy_id, tenant_id=principal.tenant_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    try:
        restored = optimization.rollback_policy(
            db,
            policy=policy,
            actor_user_id=principal.user_id,
            comment=payload.comment,
        )
        audit(db, principal, "learning.policy_rolled_back", "learning_policy", policy.id, {"restored_policy_id": restored.id})
        db.commit()
        db.refresh(restored)
        return model_to_dict(restored)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc


@router.post("/policies/{policy_id}/promote-stage")
def promote_policy_stage(
    policy_id: str,
    payload: RollbackDecision,
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    policy = db.query(LearningPolicy).filter_by(id=policy_id, tenant_id=principal.tenant_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    try:
        policy = optimization.advance_rollout(
            db,
            policy=policy,
            actor_user_id=principal.user_id,
            comment=payload.comment,
        )
        audit(db, principal, "learning.policy_rollout_advanced", "learning_policy", policy.id, {"stage": policy.status})
        db.commit()
        db.refresh(policy)
        return model_to_dict(policy)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _learning_error(exc) from exc
