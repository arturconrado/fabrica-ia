from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import get_db
from app.learning.global_registry import GlobalLearningRegistryService
from app.learning.optimization_service import LearningOptimizationError
from app.models import GlobalLearningDeployment, GlobalLearningPolicy, LearningCandidate
from app.services.serialization import model_to_dict, models_to_dict


router = APIRouter(prefix="/api/v1", tags=["global-learning"])
service = GlobalLearningRegistryService()


class PromoteRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=4000)


class DeploymentRequest(BaseModel):
    rollout_stage: Literal["shadow", "internal", "canary", "active"] = "shadow"
    expected_version: int = Field(ge=0)
    comment: str = Field(min_length=1, max_length=4000)


class RollbackRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=4000)


def _error(exc: LearningOptimizationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/admin/global-learning/policies")
def list_global_policies(
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    policies = db.query(GlobalLearningPolicy).order_by(GlobalLearningPolicy.created_at.desc()).all()
    active_deployments = (
        db.query(GlobalLearningDeployment)
        .filter_by(tenant_id=principal.tenant_id, status="active")
        .order_by(GlobalLearningDeployment.deployed_at.desc())
        .all()
    )
    deployment_by_type = {}
    for deployment in active_deployments:
        deployment_by_type.setdefault(deployment.policy_type, model_to_dict(deployment))
    rows = models_to_dict(policies)
    for row in rows:
        row["tenant_deployment"] = deployment_by_type.get(row["policy_type"])
    return rows


@router.post("/admin/global-learning/candidates/{candidate_id}/promote")
def promote_candidate(
    candidate_id: str,
    payload: PromoteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    candidate = db.query(LearningCandidate).filter_by(id=candidate_id, tenant_id=principal.tenant_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    try:
        policy = service.promote(
            db,
            candidate=candidate,
            actor_user_id=principal.user_id,
            comment=payload.comment,
            idempotency_key=idempotency_key,
        )
        db.commit()
        db.refresh(policy)
        return model_to_dict(policy)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _error(exc) from exc


@router.post("/admin/global-learning/policies/{policy_id}/deployments")
def deploy_policy(
    policy_id: str,
    payload: DeploymentRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    policy = db.get(GlobalLearningPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Global policy not found")
    try:
        deployment = service.deploy(
            db,
            tenant_id=principal.tenant_id,
            policy=policy,
            rollout_stage=payload.rollout_stage,
            actor_user_id=principal.user_id,
            comment=payload.comment,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
        )
        db.commit()
        db.refresh(deployment)
        return model_to_dict(deployment)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _error(exc) from exc


@router.post("/admin/global-learning/deployments/{deployment_id}/rollback")
def rollback_deployment(
    deployment_id: str,
    payload: RollbackRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    deployment = db.query(GlobalLearningDeployment).filter_by(id=deployment_id, tenant_id=principal.tenant_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Global deployment not found")
    try:
        restored = service.rollback(
            db,
            tenant_id=principal.tenant_id,
            deployment=deployment,
            actor_user_id=principal.user_id,
            comment=payload.comment,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
        )
        db.commit()
        db.refresh(restored)
        return model_to_dict(restored)
    except LearningOptimizationError as exc:
        db.rollback()
        raise _error(exc) from exc


@router.get("/learning/effective-policy")
def effective_policy(
    principal: Principal = Depends(require_roles("owner", "super_admin", "tenant_admin", "admin", "operator")),
    db: Session = Depends(get_db),
):
    return service.effective_policy(db, tenant_id=principal.tenant_id)
