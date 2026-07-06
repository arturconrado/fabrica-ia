import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, ensure_tenant, ensure_user_membership, get_current_principal, require_roles
from app.db.session import get_db
from app.models import Membership, Tenant, UserAccount
from app.schemas import MemberCreate, TenantCreate
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(tags=["auth"])


@router.get("/auth/me")
def me(principal: Principal = Depends(get_current_principal)):
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "subject": principal.subject,
        "email": principal.email,
        "name": principal.name,
        "role": principal.role,
        "auth_mode": principal.auth_mode,
    }


@router.get("/tenants")
def tenants(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    rows = (
        db.query(Tenant)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .filter(Membership.user_id == principal.user_id, Membership.status == "active")
        .order_by(Tenant.created_at.asc())
        .all()
    )
    return models_to_dict(rows)


@router.post("/tenants")
def create_tenant(
    payload: TenantCreate,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    tenant_id = payload.id or str(uuid.uuid4())
    tenant = ensure_tenant(db, tenant_id, payload.name)
    ensure_user_membership(db, tenant.id, principal.subject, principal.email, principal.name, "owner")
    audit(db, principal, "tenant.created", "tenant", tenant.id)
    db.commit()
    return model_to_dict(tenant)


@router.get("/tenants/{tenant_id}/members")
def members(
    tenant_id: str,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if tenant_id != principal.tenant_id:
        return []
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
        return {"status": "denied", "detail": "Cannot manage another tenant"}
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
