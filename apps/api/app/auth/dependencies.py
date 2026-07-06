import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import AuditLog, Membership, Role, Tenant, UserAccount


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    subject: str
    email: str
    name: str
    role: str
    claims: Dict[str, Any]
    auth_mode: str


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "tenant"


def ensure_tenant(db: Session, tenant_id: str, name: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant:
        return tenant
    slug = _slug(name)
    if db.query(Tenant).filter_by(slug=slug).first():
        slug = f"{slug}-{_slug(tenant_id)[:16]}"
    tenant = Tenant(id=tenant_id, name=name, slug=slug)
    db.add(tenant)
    db.flush()
    for role_name, permissions in {
        "owner": ["*"],
        "admin": ["runs:*", "projects:*", "batches:*", "learning:*", "settings:*"],
        "operator": ["runs:*", "projects:read", "batches:*", "learning:read"],
        "viewer": ["runs:read", "projects:read", "batches:read", "learning:read"],
    }.items():
        db.add(Role(id=str(uuid.uuid4()), tenant_id=tenant.id, name=role_name, permissions_json=permissions))
    db.flush()
    return tenant


def ensure_user_membership(
    db: Session,
    tenant_id: str,
    subject: str,
    email: str = "",
    name: str = "",
    role: str = "owner",
) -> tuple[UserAccount, Membership]:
    user = db.query(UserAccount).filter_by(subject=subject).first()
    if not user:
        user = UserAccount(id=str(uuid.uuid4()), subject=subject, email=email, name=name)
        db.add(user)
        db.flush()
    else:
        user.email = email or user.email
        user.name = name or user.name
    membership = db.query(Membership).filter_by(tenant_id=tenant_id, user_id=user.id).first()
    if not membership:
        membership = Membership(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user.id, role=role)
        db.add(membership)
        db.flush()
    return user, membership


def _verify_oidc_token(token: str, settings: Settings) -> Dict[str, Any]:
    if not settings.oidc_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC JWKS URL is required when auth is enabled",
        )
    try:
        import jwt
        from jwt import PyJWKClient
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise HTTPException(status_code=500, detail=f"PyJWT is not installed: {exc}") from exc

    try:
        signing_key = PyJWKClient(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        decode_kwargs: Dict[str, Any] = {"algorithms": ["RS256"], "issuer": settings.oidc_issuer_url or None}
        if settings.oidc_audience:
            decode_kwargs["audience"] = settings.oidc_audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        return jwt.decode(token, signing_key.key, **decode_kwargs)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid OIDC token: {exc}") from exc


def _claims_from_request(request: Request, settings: Settings) -> tuple[Dict[str, Any], str]:
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not token:
        token = request.query_params.get("access_token", "")
    if settings.auth_disabled:
        return {
            "sub": "local-dev-user",
            "email": "operator@local.dev",
            "name": "Local Operator",
            settings.oidc_tenant_claim: settings.default_tenant_id,
        }, "disabled"
    if settings.environment == "local" and settings.dev_auth_token and token == settings.dev_auth_token:
        return {
            "sub": "local-dev-token-user",
            "email": "operator@local.dev",
            "name": "Local Operator",
            settings.oidc_tenant_claim: settings.default_tenant_id,
        }, "dev-token"
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    return _verify_oidc_token(token, settings), "oidc"


def get_current_principal(
    request: Request,
    db: Session = Depends(get_db),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> Principal:
    settings = get_settings()
    claims, auth_mode = _claims_from_request(request, settings)
    tenant_id = x_tenant_id or request.query_params.get("tenant_id") or claims.get(settings.oidc_tenant_claim) or settings.default_tenant_id
    tenant_name = claims.get("tenant_name") or settings.default_tenant_name
    ensure_tenant(db, tenant_id, tenant_name)
    user, membership = ensure_user_membership(
        db,
        tenant_id=tenant_id,
        subject=str(claims.get("sub") or "unknown"),
        email=str(claims.get("email") or ""),
        name=str(claims.get("name") or ""),
        role="owner" if auth_mode in {"disabled", "dev-token"} else "operator",
    )
    if membership.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is not active")
    db.commit()
    return Principal(
        tenant_id=tenant_id,
        user_id=user.id,
        subject=user.subject,
        email=user.email,
        name=user.name,
        role=membership.role,
        claims=claims,
        auth_mode=auth_mode,
    )


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    allowed = set(roles)

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role == "owner" or principal.role in allowed:
            return principal
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    return dependency


def audit(
    db: Session,
    principal: Principal,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
    )


def has_any_role(principal: Principal, roles: Iterable[str]) -> bool:
    return principal.role == "owner" or principal.role in set(roles)
