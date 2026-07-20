import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.db.session import set_tenant_context
from app.models import Membership, Role, Tenant, UserAccount


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str):
    """Reuse only the provider's public signing keys across requests.

    PyJWKClient maintains an expiring, thread-safe JWK-set cache, but
    constructing a new instance for every API request defeats it. No access
    token, claim, or tenant data is cached.
    """
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url, cache_keys=True, cache_jwk_set=True, lifespan=300, timeout=5)


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
    set_tenant_context(db, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if tenant:
        return tenant
    slug = _slug(name)
    if db.query(Tenant).filter_by(slug=slug).first():
        slug = f"{slug}-{_slug(tenant_id)[:16]}"
    tenant = Tenant(id=tenant_id, name=name, slug=slug)
    db.add(tenant)
    db.flush()
    set_tenant_context(db, tenant_id)
    for role_name, permissions in {
        "owner": ["*"],
        "super_admin": ["*"],
        "tenant_admin": ["programs:*", "contracts:*", "entitlements:*", "components:*", "approvals:*", "knowledge:*", "audit:read"],
        "engagement_manager": ["programs:*", "components:*", "approvals:*", "knowledge:*", "audit:read"],
        "consultant": ["programs:read", "components:*", "approvals:*", "knowledge:*", "audit:read"],
        "client_sponsor": ["programs:read", "components:read", "approvals:*"],
        "process_owner": ["programs:read", "components:read", "approvals:*"],
        "reviewer": ["programs:read", "components:read", "approvals:*"],
        "auditor": ["programs:read", "components:read", "approvals:read", "knowledge:read", "audit:read"],
        "end_user": ["programs:read", "components:read"],
        "admin": ["runs:*", "projects:*", "batches:*", "learning:*", "knowledge:*", "settings:*"],
        "operator": ["runs:*", "projects:read", "batches:*", "learning:read", "knowledge:*"],
        "viewer": ["runs:read", "projects:read", "batches:read", "learning:read", "knowledge:read"],
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
    set_tenant_context(db, tenant_id)
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


def find_onboarded_user(
    db: Session,
    *,
    subject: str,
    email: str = "",
    name: str = "",
) -> Optional[UserAccount]:
    """Resolve an identity without granting access to any tenant.

    OIDC authentication proves who the caller is. Tenant access is granted only
    by an existing Membership created through the onboarding flow.
    """
    user = db.query(UserAccount).filter_by(subject=subject).first()
    if not user:
        return None
    user.email = email or user.email
    user.name = name or user.name
    db.flush()
    return user


def _verify_oidc_token(token: str, settings: Settings) -> Dict[str, Any]:
    if not settings.oidc_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC JWKS URL is required when auth is enabled",
        )
    try:
        import jwt
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise HTTPException(status_code=500, detail=f"PyJWT is not installed: {exc}") from exc

    try:
        signing_key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
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
    tenant_id = x_tenant_id or claims.get(settings.oidc_tenant_claim) or settings.default_tenant_id
    tenant_name = claims.get("tenant_name") or settings.default_tenant_name
    subject = str(claims.get("sub") or "unknown")
    email = str(claims.get("email") or "")
    name = str(claims.get("name") or "")

    if auth_mode in {"disabled", "dev-token"}:
        if tenant_id != settings.default_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Local authentication is restricted to the default tenant",
            )
        ensure_tenant(db, tenant_id, tenant_name)
        # RLS is enabled in homologation too. Bind the tenant before looking up
        # or creating the local membership, otherwise PostgreSQL hides it and a
        # retry can attempt to create a duplicate membership.
        set_tenant_context(db, tenant_id)
        user, membership = ensure_user_membership(
            db,
            tenant_id=tenant_id,
            subject=subject,
            email=email,
            name=name,
            role="owner",
        )
    else:
        user = find_onboarded_user(db, subject=subject, email=email, name=name)
        if not user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User onboarding is required")
        set_tenant_context(db, tenant_id, user.id)
        tenant = db.get(Tenant, tenant_id)
        if not tenant or tenant.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access is not provisioned")
        membership = db.query(Membership).filter_by(tenant_id=tenant_id, user_id=user.id).first()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is required")
    if membership.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is not active")
    set_tenant_context(db, tenant_id, user.id)
    # Do not commit here: set_config(..., true) is transaction-local. The
    # request must keep the same transaction so every downstream query remains
    # protected by the tenant RLS context.
    request.state.tenant_id = tenant_id
    request.state.user_id = user.id
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
    from app.service_delivery.ledger import append_ledger_event

    append_ledger_event(
        db,
        tenant_id=principal.tenant_id,
        aggregate_type=resource_type or "audit",
        aggregate_id=resource_id or principal.tenant_id,
        event_type=action,
        actor_user_id=principal.user_id,
        correlation_id=str((metadata or {}).get("correlation_id") or ""),
        payload=metadata or {},
    )


def has_any_role(principal: Principal, roles: Iterable[str]) -> bool:
    return principal.role == "owner" or principal.role in set(roles)
