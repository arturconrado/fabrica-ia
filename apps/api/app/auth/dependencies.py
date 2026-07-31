import uuid
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic
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


@dataclass(frozen=True)
class _Authorization:
    user_id: str
    role: str
    expires_at: float


_AUTHORIZATION_TTL_SECONDS = 2.0
_AUTHORIZATION_CACHE_MAX_ENTRIES = 2_048
_authorization_cache: OrderedDict[tuple[str, str], _Authorization] = OrderedDict()
_authorization_cache_lock = Lock()


@lru_cache(maxsize=_AUTHORIZATION_CACHE_MAX_ENTRIES)
def _authorization_key_lock(tenant_id: str, subject: str) -> Lock:
    del tenant_id, subject
    return Lock()


def _cached_authorization(tenant_id: str, subject: str) -> Optional[_Authorization]:
    key = (tenant_id, subject)
    now = monotonic()
    with _authorization_cache_lock:
        cached = _authorization_cache.get(key)
        if not cached:
            return None
        if cached.expires_at <= now:
            _authorization_cache.pop(key, None)
            return None
        _authorization_cache.move_to_end(key)
        return cached


def _remember_authorization(tenant_id: str, subject: str, user_id: str, role: str) -> None:
    key = (tenant_id, subject)
    with _authorization_cache_lock:
        _authorization_cache[key] = _Authorization(
            user_id=user_id,
            role=role,
            expires_at=monotonic() + _AUTHORIZATION_TTL_SECONDS,
        )
        _authorization_cache.move_to_end(key)
        while len(_authorization_cache) > _AUTHORIZATION_CACHE_MAX_ENTRIES:
            _authorization_cache.popitem(last=False)


def invalidate_authorization_cache(*, tenant_id: str = "", subject: str = "") -> None:
    """Expire cached RBAC decisions after an identity or membership change."""
    with _authorization_cache_lock:
        if tenant_id and subject:
            _authorization_cache.pop((tenant_id, subject), None)
            return
        for key in list(_authorization_cache):
            if (not tenant_id or key[0] == tenant_id) and (not subject or key[1] == subject):
                _authorization_cache.pop(key, None)


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "tenant"


def tenant_runtime_configuration(
    settings: Settings,
    tenant_id: str,
    *,
    onboarding_status: str,
    rag_generation_enabled: bool = False,
) -> Dict[str, Any]:
    return {
        "onboarding_status": onboarding_status,
        "build_mode": "ai_native" if settings.generative_build_enabled else "prebuild_only",
        "llm_real": "enabled" if rag_generation_enabled else "opt_in",
        "rag_generation": "enabled" if rag_generation_enabled else "extractive_only",
        "generative_build": settings.generative_build_enabled,
        "regulated_data": False,
        "storage_prefix": f"tenants/{tenant_id}/",
        "knowledge_storage_prefix": f"tenants/{tenant_id}/knowledge/",
        "limits": {
            "users": settings.pilot_max_users_per_tenant,
            "concurrent_workflows": settings.pilot_max_concurrent_workflows_per_tenant,
            "knowledge_bases": settings.knowledge_max_bases_per_tenant,
            "knowledge_documents": settings.knowledge_max_documents_per_tenant,
            "knowledge_total_chars": settings.knowledge_max_total_chars_per_tenant,
        },
    }


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
        # Non-human identity used only to aggregate release evidence for the
        # dedicated homologation tenant. Route-level RBAC deliberately grants
        # this role access to the three read-only readiness projections only.
        "release_validator": ["release:read"],
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
    operator_profile: str = "generalist",
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
        membership = Membership(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user.id,
            role=role, operator_profile=operator_profile,
        )
        db.add(membership)
        db.flush()
    invalidate_authorization_cache(tenant_id=tenant_id, subject=subject)
    return user, membership


def find_onboarded_principal(
    db: Session,
    *,
    tenant_id: str,
    subject: str,
    user_id: str = "",
) -> tuple[Optional[UserAccount], Optional[Tenant], Optional[Membership]]:
    """Resolve an identity and its tenant membership in one read.

    OIDC authentication proves who the caller is. Tenant access is granted only
    by an existing Membership created through the onboarding flow.
    """
    set_tenant_context(db, tenant_id, user_id or "oidc-authentication")
    row = (
        db.query(UserAccount, Tenant, Membership)
        .select_from(UserAccount)
        .outerjoin(Tenant, Tenant.id == tenant_id)
        .outerjoin(
            Membership,
            (Membership.tenant_id == tenant_id) & (Membership.user_id == UserAccount.id),
        )
        .filter(UserAccount.subject == subject)
        .first()
    )
    return row if row else (None, None, None)


def authorize_oidc_principal(db: Session, *, tenant_id: str, subject: str) -> tuple[str, str]:
    cached = _cached_authorization(tenant_id, subject)
    if cached:
        return cached.user_id, cached.role
    # Collapse a same-identity burst to one local RBAC query per worker.
    # Waiting sessions are still connectionless here.
    with _authorization_key_lock(tenant_id, subject):
        cached = _cached_authorization(tenant_id, subject)
        if cached:
            return cached.user_id, cached.role
        user, tenant, membership = find_onboarded_principal(
            db,
            tenant_id=tenant_id,
            subject=subject,
        )
        if not user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User onboarding is required")
        set_tenant_context(db, tenant_id, user.id)
        if not tenant or tenant.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access is not provisioned")
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is required")
        if membership.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is not active")
        _remember_authorization(tenant_id, subject, user.id, membership.role)
        return user.id, membership.role


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
        user_id, role = authorize_oidc_principal(db, tenant_id=tenant_id, subject=subject)
    if auth_mode in {"disabled", "dev-token"}:
        if membership.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is not active")
        user_id = user.id
        role = membership.role
    if auth_mode in {"disabled", "dev-token"}:
        set_tenant_context(db, tenant_id, user_id)
    else:
        db.info["tenant_id"] = tenant_id
        db.info["user_id"] = user_id
    # Never commit from authentication. PostgreSQL RLS context is
    # transaction-local and is reapplied from ``db.info`` on the next begin.
    request.state.tenant_id = tenant_id
    request.state.user_id = user_id
    principal = Principal(
        tenant_id=tenant_id,
        user_id=user_id,
        subject=subject,
        email=email,
        name=name,
        role=role,
        claims=claims,
        auth_mode=auth_mode,
    )
    if auth_mode == "oidc":
        # Release the authentication connection before FastAPI schedules the
        # synchronous endpoint. The session retains tenant/user in ``info``;
        # ``restore_tenant_context`` reapplies both values when the endpoint
        # starts its transaction. Without this boundary, enough concurrent
        # authentication dependencies can occupy every worker thread while
        # waiting for pool slots, starving the endpoints that would release
        # those same connections.
        db.rollback()
    return principal


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
