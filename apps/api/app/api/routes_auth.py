import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.auth.dependencies import Principal, audit, ensure_tenant, ensure_user_membership, get_current_principal, require_roles
from app.core.config import get_settings
from app.db.session import get_db, set_tenant_context
from app.models import Membership, Tenant, UserAccount
from app.schemas import MemberCreate, TenantCreate
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(tags=["auth"])


def _principal_payload(principal: Principal):
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "subject": principal.subject,
        "email": principal.email,
        "name": principal.name,
        "role": principal.role,
        "auth_mode": principal.auth_mode,
    }


def _accessible_tenants(db: Session, principal: Principal):
    return (
        db.query(Tenant)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .order_by(Tenant.created_at.asc())
        .execution_options(include_all_tenants=True)
        .all()
    )


@router.get("/auth/me")
def me(principal: Principal = Depends(get_current_principal)):
    return _principal_payload(principal)


@router.get("/auth/session")
def session_context(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Return the BFF bootstrap in one authenticated, tenant-bound request."""
    return {
        "me": _principal_payload(principal),
        "tenants": models_to_dict(_accessible_tenants(db, principal)),
    }


@router.get("/tenants")
def tenants(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(_accessible_tenants(db, principal))


@router.post("/tenants")
def create_tenant(
    payload: TenantCreate,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if settings.runtime_profile.lower() == "production":
        raise HTTPException(status_code=403, detail={"code": "ASSISTED_ONBOARDING_REQUIRED", "message": "Production tenants are created only by the assisted operator CLI"})
    active_tenants = db.query(Tenant).filter(Tenant.status != "deleted").count()
    if active_tenants >= settings.pilot_max_tenants:
        raise HTTPException(status_code=409, detail={"code": "PILOT_TENANT_LIMIT", "message": "Pilot tenant limit reached"})
    tenant_id = payload.id or str(uuid.uuid4())
    source_tenant_id = principal.tenant_id
    tenant = ensure_tenant(db, tenant_id, payload.name)
    tenant.status = "onboarding"
    tenant.runtime_configuration_json = {
        "onboarding_status": "pending_assisted_acceptance",
        "build_mode": "ai_native" if settings.generative_build_enabled else "prebuild_only",
        "llm_real": "opt_in",
        "rag_generation": "extractive_only",
        "generative_build": settings.generative_build_enabled,
        "regulated_data": False,
        "storage_prefix": f"tenants/{tenant.id}/",
        "knowledge_storage_prefix": f"tenants/{tenant.id}/knowledge/",
        "limits": {
            "users": settings.pilot_max_users_per_tenant,
            "concurrent_workflows": settings.pilot_max_concurrent_workflows_per_tenant,
            "knowledge_bases": settings.knowledge_max_bases_per_tenant,
            "knowledge_documents": settings.knowledge_max_documents_per_tenant,
            "knowledge_total_chars": settings.knowledge_max_total_chars_per_tenant,
        },
    }
    tenant.retention_policy_json = {"backups_days": 7, "rpo_hours": 24, "rto_target_hours": 4}
    set_tenant_context(db, tenant.id, principal.user_id)
    ensure_user_membership(db, tenant.id, principal.subject, principal.email, principal.name, "owner")
    set_tenant_context(db, source_tenant_id, principal.user_id)
    audit(db, principal, "tenant.created", "tenant", tenant.id)
    db.commit()
    return model_to_dict(tenant)


@router.post("/tenants/{tenant_id}/onboarding/accept")
def accept_tenant_onboarding(
    tenant_id: str,
    confirm: str,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if get_settings().runtime_profile.lower() == "production":
        raise HTTPException(status_code=403, detail={"code": "ASSISTED_ONBOARDING_REQUIRED", "message": "Production activation is performed only by the assisted operator CLI"})
    if confirm != "accept assisted pilot controls":
        raise HTTPException(status_code=400, detail={"code": "ONBOARDING_CONFIRMATION_REQUIRED", "message": "Invalid onboarding confirmation"})
    membership = (
        db.query(Membership)
        .filter_by(tenant_id=tenant_id, user_id=principal.user_id, status="active")
        .execution_options(include_all_tenants=True)
        .first()
    )
    tenant = db.get(Tenant, tenant_id)
    if not tenant or not membership:
        raise HTTPException(status_code=404, detail="Tenant onboarding not found")
    source_tenant_id = principal.tenant_id
    set_tenant_context(db, tenant_id, principal.user_id)
    tenant.status = "active"
    tenant.runtime_configuration_json = {
        **(tenant.runtime_configuration_json or {}),
        "onboarding_status": "accepted",
        "accepted_by": principal.user_id,
        "accepted_at": datetime.utcnow().isoformat(),
    }
    from app.service_delivery.ledger import append_ledger_event

    append_ledger_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="tenant",
        aggregate_id=tenant_id,
        event_type="tenant.onboarding_accepted",
        actor_user_id=principal.user_id,
        payload={"summary": "Assisted pilot onboarding controls accepted"},
    )
    db.commit()
    set_tenant_context(db, source_tenant_id, principal.user_id)
    return model_to_dict(tenant)


@router.get("/tenants/{tenant_id}/members")
def members(
    tenant_id: str,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot read another tenant")
    rows = (
        db.query(Membership, UserAccount)
        .join(UserAccount, Membership.user_id == UserAccount.id)
        .filter(Membership.tenant_id == tenant_id)
        .order_by(Membership.created_at.asc())
        .all()
    )
    return [
        {
            "membership": model_to_dict(membership),
            "user": model_to_dict(user),
        }
        for membership, user in rows
    ]


@router.post("/tenants/{tenant_id}/members")
def add_member(
    tenant_id: str,
    payload: MemberCreate,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot manage another tenant")
    settings = get_settings()
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 4))"), {"key": f"tenant-members:{tenant_id}"})
    existing = db.query(Membership).filter_by(tenant_id=tenant_id).count()
    known_user = db.query(UserAccount).filter_by(subject=payload.subject).first()
    known_membership = (
        db.query(Membership).filter_by(tenant_id=tenant_id, user_id=known_user.id).first()
        if known_user
        else None
    )
    if not known_membership and existing >= settings.pilot_max_users_per_tenant:
        raise HTTPException(status_code=409, detail={"code": "PILOT_USER_LIMIT", "message": "Pilot user limit reached"})
    user, membership = ensure_user_membership(
        db,
        tenant_id=tenant_id,
        subject=payload.subject,
        email=payload.email,
        name=payload.name,
        role=payload.role,
    )
    audit(db, principal, "member.added", "membership", membership.id, {"subject": user.subject, "role": membership.role})
    db.commit()
    return {"membership": model_to_dict(membership), "user": model_to_dict(user)}
